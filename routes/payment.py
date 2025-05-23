import os
import pygetwindow as gw

import sys
from flask import Blueprint, request, render_template, jsonify, session
from utils.helpers import db_fs, get_xendit_client
import requests, uuid, time, base64, pyautogui, threading
import logging
from utils.helpers import send_telegram_notification
import tkinter as tk


payment_bp = Blueprint("payment", __name__)



@payment_bp.route("/<doc_id>/start_payment_invoice", methods=["POST"])
def start_payment_invoice(doc_id):
    config_doc = db_fs.collection("Photobox").document(doc_id).get()
    if not config_doc.exists:
        return jsonify({"error": "Document not found"}), 404

    config = config_doc.to_dict()
    callback_url = f"https://services.eagleies.com/xendit_webhook?activation_id={doc_id}"

    data = {
        "external_id": str(uuid.uuid4()),
        "payer_email": "guest@example.com",
        "description": "Photobox Session",
        "amount": config.get("price", 10000),
        "currency": "IDR",
        "callback_url": callback_url,  # ✅ sudah include activation_id
        "success_redirect_url": f"/{doc_id}/payment_status",
        "failure_redirect_url": f"/{doc_id}/payment_failed"
    }

    client = get_xendit_client(config)
    response = client.post("https://api.xendit.co/v2/invoices", json=data)

    if response.status_code == 200:
        invoice = response.json()
        return jsonify({
            "invoice_url": invoice["invoice_url"],
            "invoice_id": invoice["id"]
        })
    return jsonify({"error": "Gagal membuat invoice Xendit"}), 500


@payment_bp.route("/<doc_id>/check_invoice_status/<invoice_id>")
def check_invoice_status(doc_id, invoice_id):
    config = db_fs.collection("Photobox").document(doc_id).get().to_dict()
    client = get_xendit_client(config)

    try:
        response = client.get(f"https://api.xendit.co/v2/invoices/{invoice_id}")
        if response.status_code == 200:
            return jsonify({"status": response.json().get("status")})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"error": "Gagal mengecek status invoice"}), 500


@payment_bp.route("/<doc_id>/payment_qris")
def payment_qris(doc_id):
    config = db_fs.collection("Photobox").document(doc_id).get().to_dict()

    # Prioritaskan harga voucher jika tersedia
    voucher_price = session.pop("voucher_price", None)
    price = voucher_price if voucher_price else config.get("price", 10000)

    return render_template("payment_qris.html", price_per_session=price, doc_id=doc_id)



@payment_bp.route("/<doc_id>/start_payment", methods=["POST"])
def start_payment(doc_id):
    config = db_fs.collection("Photobox").document(doc_id).get().to_dict()
    headers = {
        "Authorization": "Basic " + base64.b64encode(f"{config.get('xendit_api_key', '')}:".encode()).decode(),
        "Content-Type": "application/json"
    }
    data = {
        "external_id": str(uuid.uuid4()),
        "amount": config.get("price", 10000),
        "type": "DYNAMIC",
        "callback_url": config.get("callback_url")
    }
    response = requests.post("https://api.xendit.co/qr_codes", headers=headers, json=data)
    if response.status_code == 200:
        qr_data = response.json()
        return jsonify({"qr_string": qr_data["qr_string"], "qr_id": qr_data["id"]})
    return jsonify({"error": "Gagal membuat QRIS"}), 500


@payment_bp.route("/<doc_id>/check_qr_status/<qr_id>")
def check_qr_status(doc_id, qr_id):
    config = db_fs.collection("Photobox").document(doc_id).get().to_dict()
    headers = {
        "Authorization": "Basic " + base64.b64encode(f"{config.get('xendit_api_key', '')}:".encode()).decode(),
        "Content-Type": "application/json"
    }
    response = requests.get(f"https://api.xendit.co/qr_codes/{qr_id}", headers=headers)
    if response.status_code == 200:
        return jsonify({"status": response.json().get("status")})
    return jsonify({"error": "Gagal cek status QRIS"}), 500


@payment_bp.route("/<doc_id>/payment_status")
def payment_status(doc_id):
    return render_template("success.html", doc_id=doc_id)


@payment_bp.route("/<doc_id>/payment_failed")
def payment_failed(doc_id):
    return render_template("failed.html")


@payment_bp.route("/xendit_webhook", methods=["POST"])
def xendit_webhook():
    try:
        data = request.json
        doc_id = request.args.get("activation_id")

        logging.info(f"📩 Webhook Xendit masuk!")
        logging.info(f"📦 Data body: {data}")
        logging.info(f"🔑 Activation ID: {doc_id}")

        if data.get("status") == "PAID" and doc_id:
            amount = data.get("amount") or 0
            paid_at = data.get("paid_at") or "N/A"

            message = (
                f"✅ Pembayaran diterima!\n"
                f"📍 Booth ID: {doc_id}\n"
                f"💸 Jumlah: Rp {amount:,}\n"
                f"🕒 Waktu: {paid_at}"
            )

            logging.info("🟢 Mengirim Telegram...")
            send_telegram_notification(message)
            run_dslrbooth_session(doc_id)


        return jsonify({"status": "received"}), 200

    except Exception as e:
        logging.exception("❌ Error di webhook:")
        return jsonify({"error": str(e)}), 500

@payment_bp.route("/test_timer/<doc_id>")
def test_timer(doc_id):
    run_dslrbooth_session(doc_id)
    return "Timer triggered"



def run_dslrbooth_session(doc_id):
    config_doc = db_fs.collection("Photobox").document(doc_id).get()
    if not config_doc.exists:
        return

    config = config_doc.to_dict()
    headers = {"x-api-key": config.get("dslrbooth_api_password")}

    try:
        requests.post(config.get("dslrbooth_api_url"), headers=headers)
        logging.info("✅ DSLRBooth trigger sent")
    except Exception as e:
        logging.warning(f"❌ DSLRBooth API failed: {e}")

    time.sleep(0.5)
    pyautogui.hotkey("alt", "tab")
    time.sleep(1)

    logging.info("⏳ Memulai countdown GUI (inline)")
    threading.Thread(target=start_countdown_gui, args=(doc_id,), daemon=True).start()


def start_countdown_gui(doc_id, seconds=300):
    def run():
        for i in range(seconds, -1, -1):
            label.config(text=f"{i} s")
            time.sleep(1)
        

        # 🪟 Fokus balik ke jendela aplikasi utama
        try:
            win = gw.getWindowsWithTitle("Photobox")[0]
            win.activate()
            logging.info("✅ Fokus kembali ke jendela Photobox.")
        except Exception as e:
            logging.warning(f"❌ Gagal mengaktifkan jendela Photobox: {e}")
        root.destroy()
        # 🔁 Redirect local ke halaman awal photobox
        try:
            requests.get(f"https://services.eagleies.com//{doc_id}")
            logging.info(f"🌐 Redirect Berhasil")
        except Exception as e:
            logging.warning(f"❌ Gagal redirect ke homepage: {e}")

    root = tk.Tk()
    root.title("Countdown")
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.configure(bg='white')

    screen_width = root.winfo_screenwidth()
    window_width = 200
    window_height = 60
    x_position = int((screen_width / 2) - (window_width / 2))
    y_position = 20

    root.geometry(f"{window_width}x{window_height}+{x_position}+{y_position}")
    label = tk.Label(root, text="", font=("Poppins", 18), bg="white", fg="black")
    label.pack(expand=True)

    threading.Thread(target=run, daemon=True).start()
    root.mainloop()
