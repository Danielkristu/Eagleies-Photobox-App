import os
import threading
import time
import uuid
import base64
import requests
import logging
import webview

from flask import Flask, render_template, redirect, request, jsonify, session, flash
from flask_cors import CORS
from google.cloud import firestore
from google.cloud.firestore_v1 import FieldFilter
from datetime import timedelta
from dotenv import load_dotenv

from forms.forms import LoginForm, ActivationForm, ManageUserForm
from routes import register_routes
import tkinter as tk


# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv("SECRET_KEY", "your-secret-key-1234")
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SECURE'] = True  # Set True if HTTPS
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.permanent_session_lifetime = timedelta(minutes=15)
CORS(app)

# Webview global state
webview_window = None
photobooth_session_state = "running"

# Firestore setup
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "firebase_key.json")
db_fs = firestore.Client()

# Logging setup
if not os.path.exists('logs'):
    os.mkdir('logs')

logging.basicConfig(
    filename='logs/app.log',
    level=logging.DEBUG if app.debug else logging.WARNING,
    format='%(asctime)s [%(levelname)s] in %(module)s: %(message)s'
)

# Register blueprints
register_routes(app)


# Helper to load config

def load_config():
    activation_id = session.get("activation_id") or session.get("booth_id")
    if not activation_id:
        return {}
    doc = db_fs.collection("Photobox").document(activation_id).get()
    return doc.to_dict() if doc.exists else {}

def load_price():
    return load_config().get("price", 10000)

# Root route
from utils.helpers import get_device_mac

@app.route('/api/voucher')
def get_vouchers():
    return jsonify([
        {"id": "v1", "name": "Voucher Hemat", "price": 25000},
        {"id": "v2", "name": "Voucher Premium", "price": 50000},
    ])

@app.route("/")
def empty_home():
    activation_id = session.get("activation_id")
    print(f"[/] Session activation_id: {activation_id}")

    if not activation_id:
        print("[/] Tidak ada activation_id di session")
        return redirect("/activate")

    try:
        app_state_doc = db_fs.collection("app_state").document(activation_id).get()
        if not app_state_doc.exists:
            print(f"[/] app_state doc {activation_id} tidak ditemukan")
            return redirect("/activate")

        app_state = app_state_doc.to_dict()
        print(f"[/] app_state: {app_state}")

        if not app_state.get("is_activated", False):
            print(f"[/] app_state {activation_id} belum diaktifkan")
            return redirect("/activate")

        current_mac = get_device_mac()
        print(f"[/] Current MAC: {current_mac} | Stored: {app_state.get('device_id')}")

        if app_state.get("device_id") != current_mac:
            print(f"[/] MAC tidak cocok. Session dibersihkan.")
            session.clear()
            return redirect("/activate")

        print(f"[/] Redirecting ke /{activation_id}")
        return redirect(f"/{activation_id}")

    except Exception as e:
        logging.error("❌ Gagal verifikasi activation di /:", e)
        return redirect("/activate")




# Middleware to check activation

@app.before_request
def check_activation():
    exempt_paths = [
        "/activate", "/login", "/logout", "/manage_users",
        "/favicon.ico", "/xendit_webhook", "/session_end",
        "/dashboard", "/admin_update"
    ]

    if (
        request.path.startswith("/static/")
        or request.endpoint == "static"
        or any(request.path.startswith(p) for p in exempt_paths)
    ):
        return

    if session.get("admin_logged_in"):
        return

    if request.path.count("/") == 1 and request.path != "/":
        activation_id = session.get("activation_id")
        if not activation_id:
            return redirect("/activate")

        try:
            app_state_doc = db_fs.collection("app_state").document(activation_id).get()
            if not app_state_doc.exists:
                return redirect("/activate")

            app_state = app_state_doc.to_dict()
            if not app_state.get("is_activated", False):
                return redirect("/activate")

            current_mac = get_device_mac()
            if app_state.get("device_id") != current_mac:
                logging.warning(f"❌ Device mismatch: {current_mac} != {app_state.get('device_id')}")
                session.clear()
                return redirect("/activate")

        except Exception as e:
            logging.error("❌ Gagal validasi device:", e)
            return redirect("/activate")



# Run Flask and Webview

def start_flask():
    app.run(debug=True, use_reloader=False)

if __name__ == "__main__":
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()

    time.sleep(1)
    webview.create_window("Photobox", url="http://127.0.0.1:5000", width=1280, height=800, background_color="#ffffff")
    webview.start()
