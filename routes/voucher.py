from flask import Blueprint, request, session, redirect, render_template, flash
from utils.helpers import db_fs

voucher_bp = Blueprint("voucher", __name__)

@voucher_bp.route("/voucher_input/<doc_id>", methods=["GET"])
def voucher_input(doc_id):
    return render_template("voucher_input.html", doc_id=doc_id)

@voucher_bp.route("/use_voucher/<doc_id>", methods=["POST"])
def use_voucher(doc_id):
    code = request.form.get("voucher_code", "").strip().upper()
    print(f"🎟️ Mencoba voucher: {code} untuk doc_id: {doc_id}")

    if not code:
        flash("Kode voucher tidak boleh kosong!", "error")
        return redirect(f"/voucher_input/{doc_id}")

    voucher_doc = db_fs.collection("Photobox").document(doc_id) \
                      .collection("Vouchers").document(code).get()

    if not voucher_doc.exists:
        print(f"❌ Voucher {code} tidak ditemukan di doc_id: {doc_id}")
        flash("Voucher tidak ditemukan.", "error")
        return redirect(f"/voucher_input/{doc_id}")

    voucher_data = voucher_doc.to_dict()
    print(f"✅ Data voucher ditemukan: {voucher_data}")

    if not voucher_data.get("active", False):
        flash("Voucher sudah tidak aktif.", "error")
        return redirect(f"/voucher_input/{doc_id}")

    session["voucher_price"] = voucher_data.get("price", 10000)
    flash("Voucher berhasil digunakan!", "success")
    return redirect(f"/{doc_id}/payment_qris?voucher=1")




@voucher_bp.route("/<doc_id>/payment")
def shared_payment_page(doc_id):
    # Cek apakah ada sesi voucher
    amount = session.get("voucher_amount") if session.get("use_voucher") else None
    config = db_fs.collection("Photobox").document(doc_id).get().to_dict()

    if not amount:
        amount = config.get("price", 10000)

    return render_template("payment.html", doc_id=doc_id, amount=amount)


# Tambahkan ke register_routes(app):
# from routes.voucher import voucher_bp
# app.register_blueprint(voucher_bp)
