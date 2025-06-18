from flask import Blueprint, request, session, redirect, render_template, flash
from utils.helpers import db_fs, download_and_replace_voucher_bg, download_and_replace_qris_bg

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
            print(f"[VOUCHER_BG] Firestore voucherBg url: {bg_url}")  # <-- LOG HERE
            download_and_replace_voucher_bg(bg_url)  # Download and cache locally
        else:
            print("[VOUCHER_BG] No voucherBg document found in Firestore.")
    else:
        print("[VOUCHER_BG] No client_id in session.")
    # Always use local bg path for template
    local_bg_path = '/static/bg_cache/voucher_bg.jpg' if bg_url else ''
    return render_template("voucher_input.html", doc_id=doc_id, bg_url=local_bg_path)

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
    discount = session.get("voucher_discount")
    config = db_fs.collection("Clients").document(session.get("client_id")).collection("Booths").document(doc_id).get().to_dict()

    # Always use the discount field as price if present (even if 0)
    if discount is not None:
        try:
            price_per_session = int(discount)
        except Exception:
            price_per_session = 0
    else:
        price_per_session = config.get("settings", {}).get("price", 10000)

    # Fetch QRIS background from Firestore (same as payment_qris)
    bg_url = None
    try:
        client_id = session.get('client_id')
        if client_id:
            doc = db_fs.collection('Clients').document(client_id) \
                .collection('Booths').document(doc_id) \
                .collection('backgrounds').document('qrisBg').get()
            if doc.exists:
                bg_url = doc.to_dict().get('url')
                print(f"[QRIS_BG] Firestore qrisBg url: {bg_url}")
                download_and_replace_qris_bg(bg_url)
            else:
                print("[QRIS_BG] No qrisBg document found in Firestore.")
        else:
            print("[QRIS_BG] No client_id in session.")
    except Exception as e:
        print(f"[QRIS_BG] Error fetching QRIS background: {e}")
    local_bg_path = '/static/bg_cache/qris_bg.jpg' if bg_url else ''
    import time
    cache_buster = int(time.time())
    return render_template("payment_qris.html", doc_id=doc_id, price_per_session=price_per_session, bg_url=local_bg_path, cache_buster=cache_buster)


# Tambahkan ke register_routes(app):
# from routes.voucher import voucher_bp
# app.register_blueprint(voucher_bp)
