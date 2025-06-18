# routes/payment.py
import os
import threading
import time
import uuid
import base64
import requests
import logging
import pyautogui
import pygetwindow as gw
import tkinter as tk
import hashlib

from flask import Blueprint, jsonify, session, redirect, url_for, request, render_template
from google.cloud.exceptions import NotFound
from google.cloud import firestore
from utils.helpers import get_booth_config, get_config_for_webhook, get_xendit_client


# --- Helper Functions & Setup ---
print("=== PAYMENT_QRIS ROUTE HIT ===")
db_fs = firestore.Client()
payment_bp = Blueprint("payment", __name__)


def download_and_replace_bg(bg_url, save_path='static/bg_cache/qris_bg.jpg', url_cache_path='static/bg_cache/last_qris_bg_url.txt'):
    if not bg_url:
        return None
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    last_url = None
    if os.path.exists(url_cache_path):
        with open(url_cache_path, 'r', encoding='utf-8') as f:
            last_url = f.read().strip()
    # Only download if the URL has changed
    if last_url != bg_url or not os.path.exists(save_path):
        try:
            resp = requests.get(bg_url, timeout=10)
            if resp.status_code == 200:
                with open(save_path, 'wb') as f:
                    f.write(resp.content)
                with open(url_cache_path, 'w', encoding='utf-8') as f:
                    f.write(bg_url)
        except Exception as e:
            print(f"Failed to download background: {e}")
            return None
    return '/' + save_path.replace('\\', '/').replace(os.path.abspath(os.curdir), '').lstrip('/')

# --- Invoice Payment Routes (Already Refactored) ---
@payment_bp.route("/start_payment_invoice", methods=["POST"])
def start_payment_invoice():
    config = get_booth_config() # Uses session
    if not config:
        return jsonify({"error": "Unauthorized or booth not found"}), 401

    client = get_xendit_client(config)
    if not client:
        return jsonify({"error": "API client could not be configured"}), 500

    booth_id = session['booth_id']
    settings = config.get('settings', {})
    price = settings.get('price')
    callback_url = f"https://services.eagleies.com/xendit_webhook?booth_id={booth_id}"

    data = { "external_id": str(uuid.uuid4()), "amount": price, "description": "Photobox", "callback_url": callback_url, "success_redirect_url": url_for('payment.payment_status', _external=True) }
    response = client.post("https://api.xendit.co/v2/invoices", json=data)

    if response.status_code == 200:
        return jsonify(response.json())
    return jsonify({"error": "Failed to create Xendit invoice", "details": response.text}), 500


@payment_bp.route("/check_invoice_status/<invoice_id>")
def check_invoice_status(invoice_id):
    config = get_booth_config()
    if not config: return jsonify({"error": "Unauthorized"}), 401
    
    client = get_xendit_client(config)
    response = client.get(f"https://api.xendit.co/v2/invoices/{invoice_id}")
    if response.status_code == 200: return jsonify(response.json())
    return jsonify({"error": "Failed to check status"}), 500

# --- QRIS Payment Routes (Newly Refactored) ---
@payment_bp.route("/payment_qris")
def payment_qris():
    config = get_booth_config() # Uses session
    if not config:
        return redirect(url_for('auth.sign'))

    price = config.get('settings', {}).get('price', 35000)
    # Fetch QRIS background from Firestore
    bg_url = None
    try:
        booth_id = session.get('booth_id')
        client_id = session.get('client_id')
        if booth_id and client_id:
            doc = db_fs.collection('Clients').document(client_id) \
                .collection('Booths').document(booth_id) \
                .collection('backgrounds').document('qrisBg').get()
            if doc.exists:
                bg_url = doc.to_dict().get('url')
    except Exception as e:
        print(f"Error fetching QRIS background: {e}")
    # Always replace the old image with the new one
    local_bg_path = download_and_replace_bg(bg_url) if bg_url else None
    import time
    cache_buster = int(time.time())
    return render_template("payment_qris.html", price_per_session=price, bg_url=local_bg_path or bg_url, cache_buster=cache_buster)

@payment_bp.route("/start_payment_qris", methods=["POST"])
def start_payment_qris():
    """Creates a new QRIS payment request via Xendit (latest API version)."""
    config = get_booth_config()
    if not config:
        return jsonify({"error": "Unauthorized"}), 401

    settings = config.get('settings', {})
    booth_id = session.get('booth_id')
    # Compose reference_id as Eagleies-QRIS-{booth_id}-{uuid}
    reference_id = f"Eagleies-QRIS-{booth_id}-{uuid.uuid4()}"
    # Ensure amount is an integer and valid for Xendit
    price_raw = settings.get('price')
    try:
        if price_raw is None:
            raise ValueError('Price is None')
        if isinstance(price_raw, str):
            price_raw = price_raw.replace(',', '').replace(' ', '')
        amount = int(float(price_raw))
    except Exception as e:
        logging.error(f"[QRIS] Invalid price value in settings: {price_raw}, error: {e}")
        amount = 12000
    currency = settings.get('currency', 'IDR')
    qris_type = settings.get('qris_type', 'DYNAMIC')  # DYNAMIC or STATIC
    # Optional fields
    expires_at = settings.get('qris_expires_at')  # ISO 8601 string or None
    channel_code = settings.get('qris_channel_code')  # e.g. 'ID_DANA', 'ID_LINKAJA', 'QRPH'
    basket = settings.get('qris_basket')  # Optional: list of items
    metadata = settings.get('qris_metadata')  # Optional: dict
    webhook_url = settings.get('qris_webhook_url')  # Optional: override default callback

    # Build payload
    data = {
        "reference_id": reference_id,
        "external_id": booth_id,  # Add booth_id as external_id
        "type": qris_type,
        "currency": currency,
        "amount": amount,
    }
    if expires_at:
        data["expires_at"] = expires_at
    if channel_code:
        data["channel_code"] = channel_code
    if basket:
        data["basket"] = basket
    if metadata:
        data["metadata"] = metadata
    # Use webhook_url if set, else fallback to callback_url in settings
    if webhook_url:
        data["webhook_url"] = webhook_url
    elif settings.get("callback_url"):
        data["webhook_url"] = settings["callback_url"]
    # Prepare headers
    headers = {"api-version": "2022-07-31", "Content-Type": "application/json"}
    # Debug: Log config, payload, and headers (mask API key)
    safe_config = dict(config)
    if 'xendit_api_key' in safe_config:
        safe_config['xendit_api_key'] = '***MASKED***'
    logging.info(f"[QRIS] Using config: {safe_config}")
    logging.info(f"[QRIS] reference_id: {reference_id}, amount: {amount}, booth_id: {booth_id}")

    client = get_xendit_client(config)
    response = client.post("https://api.xendit.co/qr_codes", json=data, headers=headers)

    if response.status_code in (200, 201):
        return jsonify(response.json())
    # Log the error response from Xendit
    logging.error(f"[QRIS] Xendit error response: {response.status_code} {response.text}")
    return jsonify({"error": "Failed to create QRIS code", "details": response.text}), 500

@payment_bp.route("/check_qr_status/<qr_id>")
def check_qr_status(qr_id):
    """Checks the status of a specific QRIS payment."""
    config = get_booth_config()
    if not config:
        return jsonify({"error": "Unauthorized"}), 401
    
    client = get_xendit_client(config)
    response = client.get(f"https://api.xendit.co/qr_codes/{qr_id}")

    if response.status_code == 200:
        qr_data = response.json()
        booth_id = session.get('booth_id')
        # Parse booth_id from reference_id (format: Eagleies-QRIS-{booth_id}-{uuid})
        reference_id = qr_data.get('reference_id', '')
        parsed_booth_id = None
        try:
            parts = reference_id.split('-')
            if len(parts) >= 3:
                parsed_booth_id = parts[2]
        except Exception as e:
            parsed_booth_id = None
        if booth_id and parsed_booth_id == booth_id:
            status = qr_data.get('status', '').upper()
            if status in ("SUCCEEDED", "PAID", "COMPLETED"):
                return jsonify({"status": "payment succeed", "qr": qr_data})
            elif status == "EXPIRED":
                return jsonify({"status": "EXPIRED", "qr": qr_data})
            else:
                return jsonify({"status": "PENDING", "qr": qr_data})
        return jsonify(qr_data)
    return jsonify({"error": "Failed to check QRIS status"}), 500

# --- Other Shared Routes ---
@payment_bp.route("/voucher_input")
def voucher_input():
    if not get_booth_config(): return redirect(url_for('auth.sign'))
    return "This is the voucher page."

@payment_bp.route("/payment_status")
def payment_status():
    return render_template("success.html")

@payment_bp.route("/payment_failed")
def payment_failed():
    return render_template("failed.html")
# Note: The xendit_webhook must remain public and cannot use the session.
# It relies on the booth_id passed in the callback URL.
@payment_bp.route("/xendit_webhook", methods=["POST"])
def xendit_webhook():
    try:
        payload = request.json
        data = payload.get('data', {})
        reference_id = data.get('reference_id')
        status = data.get('status', '').upper()
        # Only log reference_id and status, not full payload
        logging.info(f"[WEBHOOK] Reference ID: {reference_id}, Status: {status}")

        if not reference_id:
            logging.warning("[WEBHOOK] No reference_id in payload['data'].")
            return jsonify({"error": "Missing reference_id in payload['data']"}), 400

        booth_id = None
        try:
            parts = reference_id.split('-')
            if len(parts) >= 3:
                booth_id = parts[2]
        except Exception as e:
            logging.warning(f"[WEBHOOK] Could not extract booth_id from reference_id: {reference_id}, error: {e}")

        if not booth_id:
            logging.warning(f"[WEBHOOK] Could not determine booth_id from reference_id: {reference_id}")
            return jsonify({"error": "Could not determine booth_id from reference_id"}), 400

        if status in ("SUCCEEDED", "PAID", "COMPLETED"):
            config = get_config_for_webhook(booth_id)
            if config:
                # Show payment success page for user (browser), otherwise just return JSON for Xendit
                if request.accept_mimetypes.accept_html and session.get('booth_id') == booth_id:
                    # Delay DSLRBooth trigger for 5 seconds after showing success page
                    def delayed_dslrbooth():
                        import time
                        time.sleep(5)
                        run_dslrbooth_session(booth_id)
                    threading.Thread(target=delayed_dslrbooth, daemon=True).start()
                    return redirect(url_for('payment.payment_status'))
                else:
                    # Xendit server-to-server: trigger DSLRBooth immediately, return JSON
                    threading.Thread(target=run_dslrbooth_session, args=(booth_id,), daemon=True).start()
                    return jsonify({"status": "received"}), 200
            else:
                logging.warning(f"[WEBHOOK] No config found for booth_id: {booth_id}")
        else:
            logging.info(f"[WEBHOOK] Payment not completed. Status: {status}")

        return jsonify({"status": "received"}), 200

    except Exception as e:
        logging.exception("[WEBHOOK] Error in webhook:")
        return jsonify({"error": str(e)}), 500




# --- DSLRBooth and GUI Functions ---
# These functions now fetch config based on the session where applicable

def run_dslrbooth_session(booth_id):
    """
    Triggers dslrbooth. This can be called from the webhook (with booth_id)
    or from a logged-in route (where it could get the id from session).
    Note: Do not handle Flask redirects or open browser tabs here. The route or frontend should handle redirecting
    to the payment success page.
    """
    booth_doc = None
    client_docs = db_fs.collection('Clients').stream()
    for client in client_docs:
        doc_ref = client.reference.collection('Booths').document(booth_id)
        doc = doc_ref.get()
        if doc.exists:
            booth_doc = doc
            break
    
    if not booth_doc:
        logging.error(f"Could not find client for booth_id: {booth_id}")
        return
        
    config = booth_doc.to_dict()
    settings = config.get("settings", {})
    print(f"[DSLRBOOTH] settings for booth {booth_id}: {settings}")  # DEBUG LOG
    # Try both possible field names for dslrbooth API URL and password
    dslr_url = settings.get("dslrbooth_api_url") or settings.get("dslrbooth_api")
    dslr_pass = settings.get("dslrbooth_api_password") or settings.get("dslrbooth_password")

    if not dslr_url or not dslr_pass:
        logging.error(f"DSLRBooth API URL or password missing for booth {booth_id}. settings: {settings}")
        return

    headers = {"x-api-key": dslr_pass}

    try:
        requests.post(dslr_url, headers=headers)
        logging.info(f"DSLRBooth trigger sent for booth {booth_id}")
    except Exception as e:
        logging.warning(f"DSLRBooth API failed: {e}")

    # Do  open the payment success page or browser tab here. 
    

    time.sleep(3)

    # Try to minimize the PyWebview window (if any)
    try:
        import pygetwindow as gw
        webview_windows = [w for w in gw.getAllTitles() if w and ("Eagleies Photobox" in w or "Photobox" in w)]
        if webview_windows:
            win = gw.getWindowsWithTitle(webview_windows[0])[0]
            win.minimize()
            logging.info(f"Minimized window: {webview_windows[0]}")
    except Exception as e:
        logging.warning(f"Could not minimize PyWebview window: {e}")
    # Now try to focus dslrBooth
    try:
        windows = gw.getAllTitles()
        dslr_windows = [w for w in windows if w and 'dslrbooth' in w.lower()]
        if dslr_windows:
            win = gw.getWindowsWithTitle(dslr_windows[0])[0]
            win.activate()
            logging.info(f"Focus switched to window: {dslr_windows[0]}")
        else:
            logging.warning("No window with 'dslrBooth' in title found. Sending alt+tab as fallback.")
            import pyautogui
            pyautogui.hotkey("alt", "tab")
    except Exception as e:
        logging.warning(f"Failed to focus dslrBooth window: {e}. Trying win32gui as fallback.")
        try:
            import win32gui, win32con
            def enumHandler(hwnd, lParam):
                if win32gui.IsWindowVisible(hwnd):
                    title = win32gui.GetWindowText(hwnd)
                    if 'dslrbooth' in title.lower():
                        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                        win32gui.SetForegroundWindow(hwnd)
                        logging.info(f"win32gui: Focused window: {title}")
            win32gui.EnumWindows(enumHandler, None)
        except Exception as e2:
            logging.warning(f"win32gui fallback also failed: {e2}. Sending alt+tab as last resort.")
            try:
                import pyautogui
                pyautogui.hotkey("alt", "tab")
            except Exception as e3:
                logging.warning(f"Fallback alt+tab also failed: {e3}")
    time.sleep(1)
