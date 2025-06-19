from flask import Blueprint, request, session, redirect, render_template, flash, jsonify
from utils.helpers import db_fs, download_and_replace_voucher_bg, download_and_replace_qris_bg, get_config_for_webhook
import uuid

voucher_bp = Blueprint("voucher", __name__)

@voucher_bp.route("/<booth_id>/voucher_input", methods=["GET"])
def voucher_input(booth_id):
    # Fetch voucherBg from Firestore
    bg_url = None
    client_id = session.get('client_id')
    if client_id:
        doc = db_fs.collection('Clients').document(client_id) \
            .collection('Booths').document(booth_id) \
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
    return render_template("voucher_input.html", booth_id=booth_id, bg_url=local_bg_path)

@voucher_bp.route("/use_voucher/<booth_id>", methods=["POST"])
def use_voucher(booth_id):
    code = request.form.get("voucher_code", "").strip().upper()
    print(f"🎟️ Mencoba voucher: {code} untuk booth_id: {booth_id}")

    if not code:
        flash("Kode voucher tidak boleh kosong!", "error")
        return redirect(f"/{booth_id}/voucher_input")

    # Firestore structure: Clients/<client_id>/Booths/<booth_id>/vouchers/<code>
    client_id = session.get('client_id')
    voucher_doc = db_fs.collection("Clients").document(client_id) \
        .collection("Booths").document(booth_id) \
        .collection("vouchers").document(code).get()

    if not voucher_doc.exists:
        print(f"❌ Voucher {code} tidak ditemukan di booth_id: {booth_id}")
        flash("Voucher tidak ditemukan.", "error")
        return redirect(f"/{booth_id}/voucher_input")

    voucher_data = voucher_doc.to_dict()
    print(f"✅ Data voucher ditemukan: {voucher_data}")

    if not voucher_data.get("is_active", False):
        flash("Voucher sudah tidak aktif.", "error")
        return redirect(f"/{booth_id}/voucher_input")

    discount = voucher_data.get("discount", 0)
    # Store voucher_code and discount in session for use in voucher_payment_qris
    session["voucher_code"] = code
    session["voucher_discount"] = discount
    flash("Voucher berhasil digunakan!", "success")
    return redirect(f"/{booth_id}/voucher_payment_qris")


@voucher_bp.route("/<doc_id>/payment_qris")
def shared_payment_page(doc_id):
    # Prevent direct access if voucher_discount is missing
    if not session.get("voucher_discount"):
        flash("Voucher tidak valid atau sudah kadaluarsa. Silakan masukkan voucher lagi.", "error")
        return redirect(f"/voucher_input/{doc_id}")
    # Cek apakah ada sesi voucher
    discount = session.get("voucher_discount")
    config = db_fs.collection("Clients").document(session.get("client_id")).collection("Booths").document(doc_id).get().to_dict()
    print(f"[VOUCHER_QRIS] session['voucher_discount']: {discount}")
    print(f"[VOUCHER_QRIS] config.settings.price: {config.get('settings', {}).get('price')}")

    # Always use the discount field as price if present (even if 0 or string)
    try:
        if discount is not None and str(discount).strip() != '':
            print(f"[VOUCHER_QRIS] Using discount as price: {discount}")
            price_per_session = int(float(discount))
        else:
            print(f"[VOUCHER_QRIS] Using settings price as fallback: {config.get('settings', {}).get('price', 10000)}")
            price_per_session = int(config.get("settings", {}).get("price", 10000))
    except Exception as e:
        print(f"[VOUCHER_QRIS] Error parsing price: {e}")
        price_per_session = 10000

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
    print(f"[VOUCHER_QRIS] Final price_per_session sent to template: {price_per_session}")
    return render_template("payment_qris.html", doc_id=doc_id, price_per_session=price_per_session, bg_url=local_bg_path, cache_buster=cache_buster)


@voucher_bp.route("/<doc_id>/start_payment_qris", methods=["POST"])
def start_payment_qris_voucher(doc_id):
    """Creates a QRIS payment with voucher discount for this booth."""
    from routes.payment import get_xendit_client  # Import here to avoid circular import
    client_id = session.get('client_id')
    if not client_id:
        return {"error": "Session expired. Silakan login ulang."}, 401
    # Fetch both booth and client config
    client_doc = db_fs.collection("Clients").document(client_id).get()
    booth_doc = db_fs.collection("Clients").document(client_id).collection("Booths").document(doc_id).get()
    if not booth_doc.exists:
        return {"error": "Booth tidak ditemukan."}, 404
    booth_config = booth_doc.to_dict() or {}
    print(f"[DEBUG] booth_config loaded for doc_id={doc_id}: {booth_config}")
    # Prefer booth-level xendit_api_key, fallback to client-level if missing
    api_key_source = None
    if 'xendit_api_key' in booth_config:
        api_key_source = 'booth'
    elif client_doc.exists:
        client_config = client_doc.to_dict() or {}
        print(f"[DEBUG] client_config loaded for client_id={client_id}: {client_config}")
        if 'xendit_api_key' in client_config:
            booth_config['xendit_api_key'] = client_config['xendit_api_key']
            api_key_source = 'client'
    print(f"[VOUCHER_QRIS] Using xendit_api_key from: {api_key_source}")
    settings = booth_config.get('settings', {})
    callback_url = settings.get("callback_url")
    if not callback_url:
        return {"error": "Callback URL tidak ditemukan di pengaturan."}, 500
    discount = session.get("voucher_discount")
    try:
        if discount is not None and str(discount).strip() != '':
            amount = int(float(discount))
        else:
            return {"error": "Voucher tidak valid atau tidak ada."}, 400
    except Exception as e:
        print(f"[VOUCHER_QRIS] Error parsing discount: {e}")
        return {"error": "Nominal voucher tidak valid."}, 400
    if amount < 1500 or amount > 10000000:
        return {"error": "Nominal QRIS harus antara 1.500 dan 10.000.000"}, 400
    reference_id = f"Eagleies-QRIS-{doc_id}-{uuid.uuid4()}"
    data = {
        "external_id": doc_id,  # booth_id as required
        "reference_id": reference_id,  # unique per request
        "type": "DYNAMIC",
        "callback_url": callback_url,
        "amount": amount,
        "currency": "IDR"
    }
    headers = {"api-version": "2022-07-31", "Content-Type": "application/json"}
    xendit_client = get_xendit_client(booth_config)
    if not xendit_client:
        print("[VOUCHER_QRIS] ERROR: xendit_api_key not found in booth_config or client_config!")
        return jsonify({"error": "API client could not be configured"}), 500
    try:
        response = xendit_client.post("https://api.xendit.co/qr_codes", json=data, headers=headers)
        if response.status_code in (200, 201):
            qr_data = response.json()
            return jsonify({
                "id": qr_data.get("id"),
                "qr_string": qr_data.get("qr_string"),
                "external_id": qr_data.get("external_id"),
                "amount": qr_data.get("amount"),
                "status": qr_data.get("status")
            })
        print(f"[VOUCHER_QRIS] Xendit error response: {response.status_code} {response.text}")
        return jsonify({"error": "Gagal membuat kode QRIS", "details": response.text}), 500
    except Exception as e:
        print(f"[VOUCHER_QRIS] Error creating payment: {str(e)}")
        return jsonify({"error": "Terjadi kesalahan sistem"}), 500


@voucher_bp.route("/<booth_id>/voucher_payment_qris")
def voucher_payment_qris(booth_id):
    # Always fetch the discount from Firestore using the voucher_code in session
    voucher_code = session.get("voucher_code")
    client_id = session.get("client_id")
    discount = 0
    if client_id and voucher_code:
        voucher_doc = db_fs.collection("Clients").document(client_id) \
            .collection("Booths").document(booth_id) \
            .collection("vouchers").document(voucher_code).get()
        if voucher_doc.exists:
            voucher_data = voucher_doc.to_dict()
            discount = voucher_data.get("discount", 35000)  # Default to 35000 if not set
            print(f"[VOUCHER_QRIS_PAGE] Firestore fetch: Voucher code: {voucher_code}, Discount: {discount}")
    try:
        discount = int(float(discount))
    except Exception:
        discount = 0
    print(f"[VOUCHER_QRIS_PAGE] Final discount used: {discount}")
    config = db_fs.collection("Clients").document(client_id).collection("Booths").document(booth_id).get().to_dict()
    print(f"[VOUCHER_QRIS_PAGE] config.settings.price: {config.get('settings', {}).get('price')}")
    price_per_session = discount
    # Fetch QRIS background from Firestore (same as payment_qris)
    bg_url = None
    try:
        if client_id:
            doc = db_fs.collection('Clients').document(client_id) \
                .collection('Booths').document(booth_id) \
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
    return render_template("payment_qris.html", booth_id=booth_id, doc_id=booth_id, price_per_session=discount, bg_url=local_bg_path, cache_buster=cache_buster, voucher_discount=discount)

@voucher_bp.route("/voucher_start_payment_qris/<doc_id>/<int:discount>", methods=["POST"])
def voucher_start_payment_qris(doc_id, discount):
    """Creates a QRIS payment with voucher discount for this booth, no session dependency."""
    from routes.payment import get_xendit_client  # Import here to avoid circular import
    client_id = session.get('client_id')
    if not client_id:
        return {"error": "Session expired. Silakan login ulang."}, 401
    # Fetch both booth and client config
    client_doc = db_fs.collection("Clients").document(client_id).get()
    booth_doc = db_fs.collection("Clients").document(client_id).collection("Booths").document(doc_id).get()
    if not booth_doc.exists:
        print(f"[DEBUG] Booth doc not found for doc_id={doc_id}, client_id={client_id}")
        return {"error": "Booth tidak ditemukan."}, 404
    booth_config = booth_doc.to_dict() or {}
    print(f"[DEBUG] booth_config loaded for doc_id={doc_id}: {booth_config}")
    # Prefer booth-level xendit_api_key, fallback to client-level if missing
    api_key_source = None
    if 'xendit_api_key' in booth_config:
        api_key_source = 'booth'
    elif client_doc.exists:
        client_config = client_doc.to_dict() or {}
        print(f"[DEBUG] client_config loaded for client_id={client_id}: {client_config}")
        if 'xendit_api_key' in client_config:
            booth_config['xendit_api_key'] = client_config['xendit_api_key']
            api_key_source = 'client'
    print(f"[VOUCHER_QRIS] Using xendit_api_key from: {api_key_source}")
    settings = booth_config.get('settings', {})
    callback_url = settings.get("callback_url")
    if not callback_url:
        return {"error": "Callback URL tidak ditemukan di pengaturan."}, 500
    try:
        amount = int(float(discount))
    except Exception as e:
        print(f"[VOUCHER_QRIS] Error parsing discount: {e}")
        return {"error": "Nominal voucher tidak valid."}, 400
    if amount < 1500 or amount > 10000000:
        return {"error": "Nominal QRIS harus antara 1.500 dan 10.000.000"}, 400
    reference_id = f"Eagleies-QRIS-{doc_id}-{uuid.uuid4()}"
    data = {
        "external_id": doc_id,
        "reference_id": reference_id,
        "type": "DYNAMIC",
        "callback_url": callback_url,
        "amount": amount,
        "currency": "IDR"
    }
    headers = {"api-version": "2022-07-31", "Content-Type": "application/json"}
    xendit_client = get_xendit_client(booth_config)
    if not xendit_client:
        print("[VOUCHER_QRIS] ERROR: xendit_api_key not found in booth_config or client_config!")
        return jsonify({"error": "API client could not be configured"}), 500
    try:
        response = xendit_client.post("https://api.xendit.co/qr_codes", json=data, headers=headers)
        if response.status_code in (200, 201):
            qr_data = response.json()
            return jsonify({
                "id": qr_data.get("id"),
                "qr_string": qr_data.get("qr_string"),
                "external_id": qr_data.get("external_id"),
                "amount": qr_data.get("amount"),
                "status": qr_data.get("status")
            })
        print(f"[VOUCHER_QRIS] Xendit error response: {response.status_code} {response.text}")
        return jsonify({"error": "Gagal membuat kode QRIS", "details": response.text}), 500
    except Exception as e:
        print(f"[VOUCHER_QRIS] Error creating payment: {str(e)}")
        return jsonify({"error": "Terjadi kesalahan sistem"}), 500


@voucher_bp.route("/voucher_check_qr_status/<doc_id>/<qr_id>")
def voucher_check_qr_status(doc_id, qr_id):
    """Checks the status of a specific QRIS payment for voucher flow."""
    from routes.payment import get_xendit_client  # Avoid circular import
    client_id = session.get('client_id')
    if not client_id:
        return jsonify({"error": "Session expired. Silakan login ulang."}), 401
    # Fetch booth config
    booth_doc = db_fs.collection("Clients").document(client_id).collection("Booths").document(doc_id).get()
    if not booth_doc.exists:
        return jsonify({"error": "Booth tidak ditemukan."}), 404
    booth_config = booth_doc.to_dict() or {}
    client = get_xendit_client(booth_config)
    if not client:
        return jsonify({"error": "Xendit API client could not be configured (missing xendit_api_key)."}), 500
    response = client.get(f"https://api.xendit.co/qr_codes/{qr_id}")
    if response.status_code == 200:
        qr_data = response.json()
        reference_id = qr_data.get('reference_id', '')
        # If reference_id is missing, try to get it from mapping
        if not reference_id and qr_id:
            ref_map_doc = db_fs.collection('QrIdToReference').document(qr_id).get()
            if ref_map_doc.exists:
                reference_id = ref_map_doc.to_dict().get('reference_id', '')
        parsed_doc_id = None
        try:
            parts = reference_id.split('-')
            if len(parts) >= 3:
                parsed_doc_id = parts[2]
        except Exception:
            pass
        # Check Firestore for payment status only if reference_id is not empty
        if reference_id:
            payment_doc = db_fs.collection('Payments').document(reference_id).get()
            if payment_doc.exists and payment_doc.to_dict().get('status') == 'PAID':
                return jsonify({"status": "payment succeed", "qr": qr_data})
        if doc_id and parsed_doc_id == doc_id:
            status = qr_data.get('status', '').upper()
            if status in ("SUCCEEDED", "PAID", "COMPLETED"):
                return jsonify({"status": "payment succeed", "qr": qr_data})
            elif status == "EXPIRED":
                return jsonify({"status": "EXPIRED", "qr": qr_data})
            elif status == "INACTIVE":
                return jsonify({"status": "PENDING", "qr": qr_data})
        return jsonify(qr_data)
    return jsonify({"error": "Failed to check QRIS status"}), 500


# Tambahkan ke register_routes(app):
# from routes.voucher import voucher_bp
# app.register_blueprint(voucher_bp)
