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
    price = settings.get('price', 10000)
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
    return render_template("payment_qris.html", price_per_session=price, bg_url=local_bg_path or bg_url)

@payment_bp.route("/start_payment_qris", methods=["POST"])
def start_payment_qris():
    """Creates a new QRIS payment request via Xendit."""
    config = get_booth_config()
    if not config:
        return jsonify({"error": "Unauthorized"}), 401

    settings = config.get('settings', {})
    data = {
        "external_id": f"photobox-qris-{uuid.uuid4()}",
        "type": "DYNAMIC",
        "amount": settings.get('price', 10000),
        "callback_url": settings.get("callback_url") # Ensure this is configured in your DB
    }
    client = get_xendit_client(config)
    response = client.post("https://api.xendit.co/qr_codes", json=data)

    if response.status_code == 200:
        return jsonify(response.json())
    return jsonify({"error": "Failed to create QRIS code"}), 500

@payment_bp.route("/check_qr_status/<qr_id>")
def check_qr_status(qr_id):
    """Checks the status of a specific QRIS payment."""
    config = get_booth_config()
    if not config:
        return jsonify({"error": "Unauthorized"}), 401
        
    client = get_xendit_client(config)
    response = client.get(f"https://api.xendit.co/qr_codes/{qr_id}")

    if response.status_code == 200:
        return jsonify(response.json())
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
        data = request.json
        booth_id = request.args.get("booth_id")

        logging.info(f"Webhook received! Data: {data}, Booth ID: {booth_id}")

        if data.get("status") == "PAID" and booth_id:
            
            # ✅ CORRECT: Uses the new helper to find the config for the webhook
            config = get_config_for_webhook(booth_id)

            if config:
                # You can now access the API key and other settings
                # client = get_xendit_client(config) 
                # run_dslrbooth_session(config) 
                logging.info(f"Payment received for booth: {config.get('name')}")
            else:
                 logging.warning(f"Webhook received for an unknown booth_id: {booth_id}")

        return jsonify({"status": "received"}), 200

    except Exception as e:
        logging.exception("Error in webhook:")
        return jsonify({"error": str(e)}), 500




# --- DSLRBooth and GUI Functions ---
# These functions now fetch config based on the session where applicable

def run_dslrbooth_session(booth_id):
    """
    Triggers dslrbooth. This can be called from the webhook (with booth_id)
    or from a logged-in route (where it could get the id from session).
    """
    # To use this function from a logged-in context, you'd call it like:
    # run_dslrbooth_session(session['booth_id'])

    # Since the webhook provides the booth_id, we need to find the full path to fetch the config.
    # This is a limitation of a stateless webhook.
    
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
    dslr_url = settings.get("dslrbooth_api_url")
    dslr_pass = settings.get("dslrbooth_api_password")

    if not dslr_url or not dslr_pass:
        logging.error(f"DSLRBooth API URL or password missing for booth {booth_id}")
        return

    headers = {"x-api-key": dslr_pass}

    try:
        requests.post(dslr_url, headers=headers)
        logging.info(f"DSLRBooth trigger sent for booth {booth_id}")
    except Exception as e:
        logging.warning(f"DSLRBooth API failed: {e}")

    time.sleep(0.5)
    pyautogui.hotkey("alt", "tab")
    time.sleep(1)

    logging.info("Starting countdown GUI")
    threading.Thread(target=start_countdown_gui, daemon=True).start()


def start_countdown_gui(seconds=300):
    """Note: This function is now independent of doc_id as it's a visual element."""
    def run():
        for i in range(seconds, -1, -1):
            label.config(text=f"{i} s")
            time.sleep(1)
        root.destroy()
        
        try:
            win = gw.getWindowsWithTitle("Photobox")[0]
            if win:
                win.activate()
            logging.info("Focus returned to Photobox window.")
        except Exception as e:
            logging.warning(f"Failed to focus Photobox window: {e}")

    root = tk.Tk()
    root.title("Countdown")
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.geometry("200x60+860+20") # Example position
    label = tk.Label(root, text="", font=("Poppins", 18), bg="white", fg="black")
    label.pack(expand=True)

    threading.Thread(target=run, daemon=True).start()
    root.mainloop()
