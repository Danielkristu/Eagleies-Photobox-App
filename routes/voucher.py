from flask import Blueprint, request, session, redirect, render_template, flash
from utils.helpers import db_fs

voucher_bp = Blueprint("voucher", __name__)

@voucher_bp.route("/voucher_input/<doc_id>", methods=["GET"])
def voucher_input(doc_id):
    # Fetch voucherBg from Firestore
    bg_url = None
    client_id = session.get('client_id')
    if client_id:
        doc = db_fs.collection('Clients').document(client_id) \
            .collection('Booths').document(doc_id) \
            .collection('backgrounds').document('voucherBg').get()
        if doc.exists:
            bg_url = doc.to_dict().get('url')
    return render_template("voucher_input.html", doc_id=doc_id, bg_url=bg_url)

@voucher_bp.route("/use_voucher/<doc_id>", methods=["POST"])
def use_voucher(doc_id):
    code = request.form.get("voucher_code", "").strip().upper()
    print(f"🎟️ Mencoba voucher: {code} untuk doc_id: {doc_id}")

    if not code:
        flash("Kode voucher tidak boleh kosong!", "error")
        return redirect(f"/voucher_input/{doc_id}")

    # Firestore structure: Clients/<client_id>/Booths/<doc_id>/vouchers/<code>
    client_id = session.get('client_id')
    voucher_doc = db_fs.collection("Clients").document(client_id) \
        .collection("Booths").document(doc_id) \
        .collection("vouchers").document(code).get()

    if not voucher_doc.exists:
        print(f"❌ Voucher {code} tidak ditemukan di doc_id: {doc_id}")
        flash("Voucher tidak ditemukan.", "error")
        return redirect(f"/voucher_input/{doc_id}")

    voucher_data = voucher_doc.to_dict()
    print(f"✅ Data voucher ditemukan: {voucher_data}")

    if not voucher_data.get("is_active", False):
        flash("Voucher sudah tidak aktif.", "error")
        return redirect(f"/voucher_input/{doc_id}")

    # Set the discount amount from Firestore
    session["voucher_discount"] = voucher_data.get("discount", 0)
    flash("Voucher berhasil digunakan!", "success")
    return redirect(f"/{doc_id}/payment_qris?voucher=1")


@voucher_bp.route("/<doc_id>/payment_qris")
def shared_payment_page(doc_id):
    # Cek apakah ada sesi voucher
    amount = session.get("voucher_amount") if session.get("use_voucher") else None
    config = db_fs.collection("Photobox").document(doc_id).get().to_dict()

    if not amount:
        amount = config.get("price", 10000)

    # Calculate price for QRIS page
    price_per_session = None
    # Try to get discount from session, else use default price
    if "voucher_discount" in session:
        price_per_session = session["voucher_discount"]
    else:
        # Fallback: get price from booth config
        client_id = session.get('client_id')
        booth_doc = db_fs.collection("Clients").document(client_id) \
            .collection("Booths").document(doc_id).get()
        if booth_doc.exists:
            price_per_session = booth_doc.to_dict().get("settings", {}).get("price", 10000)
        else:
            price_per_session = 10000

    return render_template("payment_qris.html", doc_id=doc_id, price_per_session=price_per_session)


# Tambahkan ke register_routes(app):
# from routes.voucher import voucher_bp
# app.register_blueprint(voucher_bp)
