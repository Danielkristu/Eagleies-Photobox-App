# utils/helpers.py
import os
import base64
import requests
import logging
import sys
import shutil
# Always set GOOGLE_APPLICATION_CREDENTIALS to the root of the bundle, not utils/
base_dir = getattr(sys, '_MEIPASS', os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

from flask import session
from google.cloud import firestore
from getmac import get_mac_address # ✅ RESTORED: Import for the MAC address function

# --- Firestore Client Initialization ---
# Set GOOGLE_APPLICATION_CREDENTIALS for Firestore access
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.path.join(base_dir, "serviceAccountKey.json")
# Initialize the client once here to be shared across the application
try:
    db_fs = firestore.Client()
except Exception as e:
    logging.error(f"Failed to initialize Firestore client in helpers: {e}")
    db_fs = None

# --- Session-Based Helper with Logging ---
def get_booth_config():
    """
    Securely fetches the configuration for the currently logged-in booth.
    It fetches the main booth document and merges it with data from the
    'settings' field (if present), the 'settings' subcollection, and merges in fields from the parent client document (e.g., xendit_api_key).
    """
    if 'client_id' not in session or 'booth_id' not in session:
        logging.warning("GET_CONFIG: Attempted to get config without a valid session.")
        print(f"[DEBUG] get_booth_config: session missing client_id or booth_id. session={dict(session)}")
        return None

    try:
        client_id = session['client_id']
        booth_id = session['booth_id']
        logging.info(f"GET_CONFIG: Attempting to fetch config for ClientID: {client_id}, BoothID: {booth_id}")
        logging.info(f"[DEBUG] get_booth_config: client_id={client_id}, booth_id={booth_id}")
        logging.info(f"[DEBUG] get_booth_config: session={dict(session)}")

        # 1. Fetch the main booth document
        booth_doc_ref = db_fs.collection('Clients').document(client_id).collection('Booths').document(booth_id)
        booth_doc = booth_doc_ref.get()

        if not booth_doc.exists:
            logging.warning(f"❌ GET_CONFIG: Main booth document not found for BoothID: {booth_id}")
            logging.info(f"[DEBUG] get_booth_config: booth_doc not found for client_id={client_id}, booth_id={booth_id}")
            return None
        
        booth_data = booth_doc.to_dict()
        logging.info(f"✅ GET_CONFIG: Found main booth document.")
        logging.info(f"[DEBUG] booth_data after fetch: {booth_data}")

        # --- FIX: Always ensure 'settings' is present and is a dict ---
        if 'settings' not in booth_data or not isinstance(booth_data['settings'], dict):
            booth_data['settings'] = {}
            print(f"[DEBUG] No settings found in booth_data, defaulting to empty dict.")

        settings_field_merged = False
        # 2. Merge 'settings' field if present in booth document
        if 'settings' in booth_data:
            logging.info(f"[DEBUG] settings field type: {type(booth_data['settings'])}, value: {booth_data['settings']}")
        if 'settings' in booth_data and isinstance(booth_data['settings'], dict):
            # Do NOT flatten settings into booth_data, just keep as booth_data['settings']
            logging.info(f"✅ GET_CONFIG: 'settings' field present in booth document.")
            settings_field_merged = True

        # 3. Fetch the settings from the subcollection
        settings_collection_ref = booth_doc_ref.collection('settings')
        settings_docs = list(settings_collection_ref.limit(1).stream())
        settings_subcol_merged = False
        if settings_docs:
            settings_data = settings_docs[0].to_dict()
            logging.info(f"✅ GET_CONFIG: Found settings document in subcollection.")
            print(f"[DEBUG] settings subcollection data: {settings_data}")
            booth_data['settings'].update(settings_data)
            settings_subcol_merged = True

        if not settings_field_merged and not settings_subcol_merged:
            logging.warning(f"⚠️ GET_CONFIG: No settings found in either the 'settings' field or subcollection for BoothID: {booth_id}. API keys might be missing.")
            print(f"[DEBUG] get_booth_config: No settings found in booth doc or subcollection for booth_id={booth_id}")

        # 4. Fetch and merge parent client document fields (e.g., xendit_api_key)
        client_doc_ref = db_fs.collection('Clients').document(client_id)
        client_doc = client_doc_ref.get()
        if client_doc.exists:
            client_data = client_doc.to_dict()
            if 'xendit_api_key' in client_data:
                booth_data['xendit_api_key'] = client_data['xendit_api_key']
            for k, v in client_data.items():
                if k not in booth_data:
                    booth_data[k] = v
            logging.info(f"✅ GET_CONFIG: Merged parent client document fields into config.")
        else:
            logging.warning(f"⚠️ GET_CONFIG: Parent client document not found for ClientID: {client_id}.")
            print(f"[DEBUG] get_booth_config: client_doc not found for client_id={client_id}")

        # Log the xendit_api_key for debug
        api_key = booth_data.get('xendit_api_key')
        logging.info(f"[DEBUG] booth_data after all merging: {booth_data}")
        if api_key:
            logging.info(f"[GET_CONFIG] xendit_api_key found: {api_key}")
        else:
            logging.warning(f"[GET_CONFIG] xendit_api_key is missing in merged config!")
            print(f"[GET_CONFIG] xendit_api_key is missing in merged config!")

        return booth_data

    except Exception as e:
        logging.error(f"❌ GET_CONFIG: An exception occurred: {e}")
        print(f"[EXCEPTION] GET_CONFIG: {e}")
        return None

# --- Xendit API Helper with Detailed Logging ---
class XenditAuth(requests.auth.AuthBase):
    def __init__(self, api_key):
        self.api_key = api_key

    def __call__(self, r):
        r.headers['Authorization'] = f"Basic {base64.b64encode(f'{self.api_key}:'.encode()).decode()}"
        return r

def get_xendit_client(config):
    """
    Creates a requests session with the correct Xendit API key from the config.
    Logs the extracted API key (masked) and whether extraction succeeded or failed.
    """
    if not config:
        logging.error("❌ XENDIT_CLIENT: Received no config to create client.")
        print("[XENDIT_CLIENT] No config provided.")
        return None
    logging.info(f"XENDIT_CLIENT: Received config. Looking for 'xendit_api_key'.")
    api_key = config.get('xendit_api_key')
    if not api_key:
        logging.error("❌ XENDIT_CLIENT: The 'xendit_api_key' is missing from the configuration.")
        print("[XENDIT_CLIENT] API key extraction FAILED: key not found in config.")
        return None
    masked_key = f"{api_key[:5]}...{api_key[-4:]}" if len(api_key) > 9 else api_key
    logging.info(f"✅ XENDIT_CLIENT: Successfully extracted API key: {masked_key}")
    print(f"[XENDIT_CLIENT] API key extraction SUCCESS: {masked_key}")
    session_req = requests.Session()
    session_req.headers.update({'Content-Type': 'application/json'})
    session_req.auth = XenditAuth(api_key)
    return session_req

# --- Webhook Helper ---

def get_config_for_webhook(booth_id):
    """
    Fetches a booth's configuration using only the booth_id.
    Merges booth doc, 'settings' field, 'settings' subcollection, and parent client doc fields (e.g., xendit_api_key).
    This is intended for stateless calls like webhooks.
    """
    if not booth_id or not db_fs:
        return None
    
    client_docs = db_fs.collection('Clients').stream()
    for client in client_docs:
        doc_ref = client.reference.collection('Booths').document(booth_id)
        doc = doc_ref.get()
        if doc.exists:
            logging.info(f"Webhook found config for booth {booth_id} under client {client.id}")
            booth_data = doc.to_dict()
            print(f"[DEBUG] get_config_for_webhook: booth_id={booth_id}, client_id={client.id}")
            logging.info(f"[DEBUG] booth_data after fetch: {booth_data}")
            settings_field_merged = False
            if 'settings' in booth_data:
                print(f"[DEBUG] settings field type: {type(booth_data['settings'])}, value: {booth_data['settings']}")
            if 'settings' in booth_data and isinstance(booth_data['settings'], dict):
                booth_data.update(booth_data['settings'])
                logging.info(f"Webhook: merged 'settings' field from booth doc.")
                del booth_data['settings']
                settings_field_merged = True
            settings_collection_ref = doc_ref.collection('settings')
            settings_docs = list(settings_collection_ref.limit(1).stream())
            settings_subcol_merged = False
            if settings_docs:
                settings_data = settings_docs[0].to_dict()
                booth_data.update(settings_data)
                logging.info(f"Webhook: merged settings subcollection doc.")
                settings_subcol_merged = True
            if not settings_field_merged and not settings_subcol_merged:
                logging.warning(f"Webhook: No settings found in either the 'settings' field or subcollection for BoothID: {booth_id}. API keys might be missing.")
            client_doc = client.reference.get()
            if client_doc.exists:
                client_data = client_doc.to_dict()
                for k, v in client_data.items():
                    if k not in booth_data:
                        booth_data[k] = v
                logging.info(f"Webhook: merged parent client doc fields.")
            # Special logic: always use parent client xendit_api_key if booth_data is missing or empty
            parent_api_key = client_data.get('xendit_api_key')
            booth_api_key = booth_data.get('xendit_api_key')
            if parent_api_key and (not booth_api_key or not isinstance(booth_api_key, str) or not booth_api_key.strip()):
                booth_data['xendit_api_key'] = parent_api_key
            api_key = booth_data.get('xendit_api_key')
            print(f"[DEBUG] booth_data after all merging: {booth_data}")
            if api_key:
                print(f"[WEBHOOK CONFIG] xendit_api_key found: {api_key}")
                logging.info(f"[WEBHOOK CONFIG] xendit_api_key found: {api_key}")
            else:
                print(f"[WEBHOOK CONFIG] xendit_api_key is missing in merged config!")
                logging.warning(f"[WEBHOOK CONFIG] xendit_api_key is missing in merged config!")
            return booth_data
    logging.warning(f"Webhook could not find any config for booth_id: {booth_id}")
    return None

# --- Xendit API Helper ---
# Using the class-based auth from your old code for a clean implementation.


# --- Telegram Helper ---

def send_telegram_notification(message: str):
    """Sends a notification message to a pre-configured Telegram chat."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        logging.warning("Telegram token/chat_id is not configured in .env file.")
        return

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message}

    try:
        response = requests.post(url, data=payload)
        response.raise_for_status()
        logging.info("Telegram notification sent successfully!")
    except Exception as e:
        logging.error(f"Failed to send Telegram notification: {e}")

def load_config(session):
    activation_id = session.get("activation_id") or session.get("booth_id")

    if not activation_id:
        return {}

    doc = db_fs.collection("Clients").document(activation_id).get()

    return doc.to_dict() if doc.exists else {}



def get_device_mac():
    """Gets the primary MAC address of the device."""
    return get_mac_address() or "unknown_mac"

VOUCHER_BG_CACHE_PATH = os.path.join("static", "bg_cache", "voucher_bg.jpg")
VOUCHER_BG_URL_PATH = os.path.join("static", "bg_cache", "last_voucher_bg_url.txt")

def download_and_replace_voucher_bg(bg_url):
    """
    Download and cache the voucher background image locally if the URL has changed.
    """
    if not bg_url:
        return
    # Check if the last URL is the same
    last_url = None
    if os.path.exists(VOUCHER_BG_URL_PATH):
        with open(VOUCHER_BG_URL_PATH, "r", encoding="utf-8") as f:
            last_url = f.read().strip()
    if last_url == bg_url and os.path.exists(VOUCHER_BG_CACHE_PATH):
        return  # Already cached
    # Download and replace
    try:
        resp = requests.get(bg_url, timeout=10)
        if resp.status_code == 200:
            with open(VOUCHER_BG_CACHE_PATH, "wb") as f:
                f.write(resp.content)
            with open(VOUCHER_BG_URL_PATH, "w", encoding="utf-8") as f:
                f.write(bg_url)
    except Exception as e:
        logging.error(f"Failed to download voucher background: {e}")

QRIS_BG_CACHE_PATH = os.path.join("static", "bg_cache", "qris_bg.jpg")
QRIS_BG_URL_PATH = os.path.join("static", "bg_cache", "last_qris_bg_url.txt")

def download_and_replace_qris_bg(bg_url):
    """
    Download and cache the QRIS background image locally if the URL has changed.
    """
    if not bg_url:
        return
    last_url = None
    if os.path.exists(QRIS_BG_URL_PATH):
        with open(QRIS_BG_URL_PATH, "r", encoding="utf-8") as f:
            last_url = f.read().strip()
    if last_url == bg_url and os.path.exists(QRIS_BG_CACHE_PATH):
        return  # Already cached
    try:
        resp = requests.get(bg_url, timeout=10)
        if resp.status_code == 200:
            with open(QRIS_BG_CACHE_PATH, "wb") as f:
                f.write(resp.content)
            with open(QRIS_BG_URL_PATH, "w", encoding="utf-8") as f:
                f.write(bg_url)
    except Exception as e:
        logging.error(f"Failed to download QRIS background: {e}")

HOME_BG_CACHE_PATH = os.path.join("static", "bg_cache", "home_bg.jpg")
HOME_BG_URL_PATH = os.path.join("static", "bg_cache", "last_home_bg_url.txt")

def download_and_replace_home_bg(bg_url):
    """
    Download and cache the home background image locally if the URL has changed.
    """
    if not bg_url:
        return
    last_url = None
    if os.path.exists(HOME_BG_URL_PATH):
        with open(HOME_BG_URL_PATH, "r", encoding="utf-8") as f:
            last_url = f.read().strip()
    if last_url == bg_url and os.path.exists(HOME_BG_CACHE_PATH):
        return  # Already cached
    try:
        resp = requests.get(bg_url, timeout=10)
        if resp.status_code == 200:
            with open(HOME_BG_CACHE_PATH, "wb") as f:
                f.write(resp.content)
            with open(HOME_BG_URL_PATH, "w", encoding="utf-8") as f:
                f.write(bg_url)
    except Exception as e:
        logging.error(f"Failed to download Home background: {e}")