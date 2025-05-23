import base64
import logging
import requests
import requests
import os
import uuid
from google.cloud import firestore
from getmac import get_mac_address

# Firestore client (can be reused across app)
db_fs = firestore.Client()


def get_device_mac():
    return get_mac_address() or "unknown_mac"



def load_config(session):
    activation_id = session.get("activation_id") or session.get("booth_id")
    if not activation_id:
        return {}
    doc = db_fs.collection("Photobox").document(activation_id).get()
    return doc.to_dict() if doc.exists else {}

def load_price(session):
    return load_config(session).get("price", 10000)

class XenditAuth(requests.auth.AuthBase):
    def __init__(self, api_key):
        self.api_key = api_key

    def __call__(self, r):
        r.headers['Authorization'] = f"Basic {base64.b64encode(f'{self.api_key}:'.encode()).decode()}"
        return r

def get_xendit_client(config):
    session_req = requests.Session()
    session_req.headers.update({'Content-Type': 'application/json'})
    session_req.auth = XenditAuth(config.get("xendit_api_key", ""))
    return session_req

def get_or_set_device_id():
    from flask import session
    if "device_id" not in session:
        session["device_id"] = str(uuid.uuid4())
    return session["device_id"]

def send_telegram_notification(message: str):
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        print("🚫 Telegram token/chat_id belum diatur!")
        return

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message
    }

    try:
        response = requests.post(url, data=payload)
        response.raise_for_status()
        print("✅ Notifikasi Telegram berhasil dikirim!")
    except Exception as e:
        print("❌ Gagal kirim Telegram:", e)