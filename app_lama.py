import os
import threading
import time
import uuid
import base64
import json
import requests
from flask import Flask, render_template, redirect, request, jsonify, session, flash
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from requests.auth import AuthBase
from dotenv import load_dotenv
import pyautogui
import webview
import time
from datetime import timedelta
from werkzeug.security import generate_password_hash
from google.cloud import firestore

# Setup Firestore
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "firebase_key.json"  # nama file key-mu
db_fs = firestore.Client()



# Load .env
load_dotenv()

app = Flask(__name__)
CORS(app)
app.secret_key = os.urandom(24)
app.permanent_session_lifetime = timedelta(minutes=5)

# SQLAlchemy setup
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///config.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Environment variables
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
XENDIT_API_KEY = os.getenv("XENDIT_API_KEY")
CALLBACK_URL = os.getenv("CALLBACK_URL")
DSLRBOOTH_API_URL = os.getenv("DSLRBOOTH_API_URL")
DSLRBOOTH_API_PASSWORD = os.getenv("DSLRBOOTH_API_PASSWORD")


# State
photobooth_session_state = "running"


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True)
    password = db.Column(db.String(100))
    booth_id = db.Column(db.String(50))  # ⬅️ referensi booth spesifik



class Booth(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    booth_code = db.Column(db.String(100), unique=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    is_activated = db.Column(db.Boolean, default=False)

class Activation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(100), nullable=False)
    is_activated = db.Column(db.Boolean, default=False)

class AppState(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    is_activated = db.Column(db.Boolean, default=False)
    activation_code = db.Column(db.String(50), nullable=True)

with app.app_context():
    db.create_all()
    if not AppState.query.first():
        db.session.add(AppState(is_activated=False))
        db.session.commit()

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = User.query.filter_by(username=request.form["username"]).first()
        if user and user.password == request.form["password"]:
            session["admin_logged_in"] = True
            session["admin_username"] = user.username
            session["booth_id"] = user.booth_id
            return redirect("/admin_dashboard")
        else:
            return "Username atau Password salah", 403
    return render_template("login.html")

@app.route("/activate", methods=["GET", "POST"])
def activate():
    state = AppState.query.first()

    # Jika sudah aktif, langsung redirect
    if state and state.is_activated:
        return redirect("/login")

    if request.method == "POST":
        entered_code = request.form.get("activation_code")

        # Cari booth berdasarkan kode yang dimasukkan
        booth = Booth.query.filter_by(booth_code=entered_code).first()

        if booth:
            # Tandai booth aktif
            booth.is_activated = True

            # Tandai aplikasi aktif
            if not state:
                state = AppState(is_activated=True, activation_code=entered_code)
                db.session.add(state)
            else:
                state.is_activated = True
                state.activation_code = entered_code

            db.session.commit()
            return redirect("/login")

        return "Activation code tidak valid (booth_code tidak ditemukan)", 403

    # Hanya jalankan ini kalau GET
    return render_template("activation.html")









# Model database
class AppConfig(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    price_per_session = db.Column(db.Integer, nullable=False, default=10000)
    xendit_api_key = db.Column(db.String(255))
    callback_url = db.Column(db.String(255))
    dslrbooth_api_url = db.Column(db.String(255))
    dslrbooth_api_password = db.Column(db.String(255))

# Buat table dan entry default
with app.app_context():
    db.create_all()
    if not AppConfig.query.first():
        db.session.add(AppConfig(
            price_per_session=10000,
            xendit_api_key="",
            callback_url="",
            dslrbooth_api_url="",
            dslrbooth_api_password=""
        ))
        db.session.commit()


@app.before_request
def init_config():
    if AppConfig.query.first() is None:
        db.session.add(AppConfig(
            price_per_session=10000,
            xendit_api_key='',
            callback_url='',
            dslrbooth_api_url='',
            dslrbooth_api_password=''
        ))
        db.session.commit()

# Create tables if not exist
with app.app_context():
    db.create_all()
    if not AppConfig.query.first():
        default_config = AppConfig(price_per_session=10000)
        db.session.add(default_config)
        db.session.commit()

# Utility functions
def load_price():
    config = load_config()
    return config.get("price", 10000)


class XenditAuth(AuthBase):
    def __init__(self, api_key):
        self.api_key = api_key

    def __call__(self, r):
        r.headers['Authorization'] = f"Basic {base64.b64encode(f'{self.api_key}:'.encode()).decode()}"
        return r

def get_xendit_client():
    session = requests.Session()
    session.headers.update({'Content-Type': 'application/json'})
    session.auth = XenditAuth(XENDIT_API_KEY)
    return session

@app.before_request
def check_activation():
    exempt_routes = ["/activate", "/static/", "/favicon.ico", "/manage_users","login",'/']  # tambahkan /manage_users
    if any(request.path.startswith(r) for r in exempt_routes):
        return
    state = AppState.query.first()
    if not state or not state.is_activated:
        return redirect("/activate")



@app.route("/manage_users", methods=["GET", "POST"])
def manage_users():
   

    if request.method == "POST":
        user_id = request.form.get("user_id")
        username = request.form["username"]
        password = request.form["password"]
        booth_id = request.form["booth_id"]

        if user_id:  # UPDATE
            user = User.query.get(int(user_id))
            if user:
                user.username = username
                if password.strip():
                    user.password = generate_password_hash(password)
                user.booth_id = booth_id
                flash("User berhasil diperbarui!", "success")
        else:  # CREATE
            if User.query.filter_by(username=username).first():
                flash("Username sudah digunakan!", "error")
            else:
                new_user = User(
                    username=username,
                    password=generate_password_hash(password),
                    booth_id=booth_id
                )
                db.session.add(new_user)
                flash("User berhasil dibuat!", "success")
        db.session.commit()

    users = User.query.all()
    return render_template("manage_users.html", users=users)

@app.route("/delete_user/<int:user_id>")
def delete_user(user_id):
    if not session.get("admin_logged_in"):
        return redirect("/login")

    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    flash("User berhasil dihapus.", "success")
    return redirect("/manage_users")

# Routes
@app.before_request
def make_session_permanent():
    session.permanent = True

@app.route("/")
def home():
    global photobooth_session_state
    photobooth_session_state = "running"
    return render_template("index.html", price_per_session=load_price())

@app.route("/admin_dashboard")
def admin_dashboard():
    
    client = get_xendit_client()
    try:
        response = client.get("https://api.xendit.co/v2/invoices")
        transactions = response.json() if response.status_code == 200 else []
    except:
        transactions = []

    total_paid = sum(tx['amount'] for tx in transactions if tx.get('status') == 'PAID')
    count_paid = len([tx for tx in transactions if tx.get('status') == 'PAID'])

    config_from_db = load_config()

    return render_template("admin_dashboard.html",
        total_paid=total_paid,
        count_paid=count_paid,
        price_per_session=config_from_db.get("price", 10000),
        config=config_from_db,
        transactions_json=json.dumps(transactions)
    )


@app.route("/admin_update", methods=["POST"])
def admin_update():
    if not session.get("admin_logged_in"):
        return redirect("/login")

    config_ref = db_fs.collection("Photobox").document("jS6z4spCgEwypZNWltdw")
    config_ref.set({
    "price": int(request.form["price_per_session"]),
    "xendit_api_key": request.form["xendit_api_key"],
    "callback_url": request.form["callback_url"],
    "dslrbooth_api_url": request.form["dslrbooth_api_url"],
    "dslrbooth_api_password": request.form["dslrbooth_api_password"],
}, merge=True)

    return redirect("/admin_dashboard")

def load_config():
    doc_ref = db_fs.collection("Photobox").document("jS6z4spCgEwypZNWltdw")
    doc = doc_ref.get()
    return doc.to_dict() if doc.exists else {}




@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.route("/start_payment", methods=["POST"])
def start_payment():
    headers = {
        "Authorization": "Basic " + base64.b64encode(f"{XENDIT_API_KEY}:".encode()).decode(),
        "Content-Type": "application/json"
    }
    data = {
        "external_id": str(uuid.uuid4()),
        "amount": load_price(),
        "type": "DYNAMIC",
        "callback_url": CALLBACK_URL
    }
    response = requests.post("https://api.xendit.co/qr_codes", headers=headers, json=data)
    if response.status_code == 200:
        qr_data = response.json()
        return jsonify({"qr_string": qr_data["qr_string"], "qr_id": qr_data["id"]})
    return jsonify({"error": "Gagal membuat QRIS"}), 500

@app.route("/start_payment_invoice", methods=["POST"])
def start_payment_invoice():
    try:
        client = get_xendit_client()
        config = load_config()

        print("🛠 Loaded config:", config)

        data = {
            "external_id": str(uuid.uuid4()),
            "payer_email": "guest@example.com",
            "description": "Photobox Session",
            "amount": load_price(),
            "currency": "IDR",
            "callback_url": config.get("callback_url", ""),
            "success_redirect_url": "https://services.eagleies.com/payment_status",
            "failure_redirect_url": "https://services.eagleies.com/payment_failed"
        }

        print("📤 Sending data to Xendit:", data)

        response = client.post("https://api.xendit.co/v2/invoices", json=data)

        print("📥 Response status:", response.status_code)
        print("📥 Response body:", response.text)

        if response.status_code == 200:
            invoice = response.json()
            return jsonify({"invoice_url": invoice["invoice_url"], "invoice_id": invoice["id"]})

        return jsonify({
            "error": "Xendit invoice failed",
            "details": response.text,
            "status_code": response.status_code
        }), 500

    except Exception as e:
        print("❌ ERROR saat membuat invoice:", str(e))
        return jsonify({"error": "Internal Server Error", "message": str(e)}), 500




@app.route("/payment_qris")
def payment_qris():
    return render_template("payment_qris.html", price_per_session=load_price())

@app.route("/admin_add_user", methods=["POST"])
def admin_add_user():
    if not session.get("admin_logged_in"):
        return redirect("/login")

    username = request.form["username"]
    password = request.form["password"]
    booth_id = request.form["booth_id"]

    hashed_pw = generate_password_hash(password)  # dari werkzeug.security

    new_user = User(username=username, password=hashed_pw, booth_id=booth_id)
    db.session.add(new_user)
    db.session.commit()

    return redirect("/admin_dashboard")


@app.route("/payment_status")
def payment_status():
    return render_template("success.html")

@app.route("/payment_failed")
def payment_failed():
    return render_template("failed.html")

@app.route("/trigger_dslrbooth", methods=["POST"])
def trigger_dslrbooth_endpoint():
    try:
        threading.Thread(target=trigger_dslrbooth).start()
        return jsonify({"status": "triggered"}), 200
    except Exception as e:
        print("Error in trigger_dslrbooth route:", e)
        return jsonify({"error": str(e)}), 500

def trigger_dslrbooth():
    try:
        api_url = os.getenv("DSLRBOOTH_API_URL")
        api_key = os.getenv("DSLRBOOTH_API_PASSWORD")
        headers = {"x-api-key": api_key}

        response = requests.post(api_url, headers=headers)
        print("dslrBooth triggered:", response.status_code, response.text)

        # Fokus ke DSLRBooth
        time.sleep(0.5)
        pyautogui.keyDown('alt')
        pyautogui.press('tab')
        pyautogui.keyUp('alt')

    except Exception as e:
        print("Error triggering dslrBooth:", e)


@app.route("/xendit_webhook", methods=["POST"])
def xendit_webhook():
    data = request.json
    if data.get("status") == "PAID":
        threading.Thread(target=trigger_dslrbooth).start()
    return jsonify({"status": "received"}), 200

@app.route("/check_session_state")
def check_session_state():
    global photobooth_session_state
    return jsonify({"state": photobooth_session_state})


@app.route("/check_qr_status/<qr_id>")
def check_qr_status(qr_id):
    api_key = os.getenv("XENDIT_API_KEY")
    headers = {
        "Authorization": "Basic " + base64.b64encode(f"{api_key}:".encode()).decode(),
        "Content-Type": "application/json"
    }
    response = requests.get(f"https://api.xendit.co/qr_codes/{qr_id}", headers=headers)
    if response.status_code == 200:
        return jsonify({"status": response.json().get("status")})
    return jsonify({"error": "Gagal cek status QRIS"}), 500

@app.route("/session_end")
def session_end():
    global photobooth_session_state
    event_type = request.args.get("event_type")

    print(f"🔍 event_type diterima: {event_type}")  # DEBUG

    if event_type and event_type.strip().lower() == "session_end":
        photobooth_session_state = "ended"
        print("✅ Session ended. Menjalankan ALT+TAB...")

        try:
            time.sleep(0.5)
            pyautogui.keyDown('alt')
            pyautogui.press('tab')
            pyautogui.keyUp('alt')
            print("🎯 Alt+Tab berhasil dijalankan")
        except Exception as e:
            print("❌ Gagal alt+tab:", e)

        return "Session ended", 200

    print("⚠️ Event bukan session_end. Tidak menjalankan Alt+Tab.")
    return "Event belum selesai", 200



@app.route("/check_invoice_status/<invoice_id>")
def check_invoice_status(invoice_id):
    client = get_xendit_client()
    response = client.get(f"https://api.xendit.co/v2/invoices/{invoice_id}")
    if response.status_code == 200:
        return jsonify({"status": response.json().get("status")})
    return jsonify({"error": "Gagal cek status invoice"}), 500


# Running
if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(debug=True, use_reloader=False)).start()
    time.sleep(2)
    webview.create_window("Photobox", url="http://127.0.0.1:5000", width=1280, height=800, background_color="#ffffff")
    webview.start()
