from flask import Blueprint, render_template, redirect, request, session, flash
from forms.forms import ManageUserForm
from utils.helpers import load_config, db_fs, get_xendit_client

dashboard_bp = Blueprint("dashboard", __name__)

@dashboard_bp.route("/dashboard")
def dashboard():
    if not session.get("admin_logged_in"):
        return redirect("/login")

    booth_id = session.get("booth_id")
    config = load_config(session)
    client = get_xendit_client(config)

    # Ambil transaksi dari Xendit
    try:
        response = client.get("https://api.xendit.co/v2/invoices")
        transactions = response.json() if response.status_code == 200 else []
    except:
        transactions = []

    total_paid = sum(tx['amount'] for tx in transactions if tx.get('status') == 'PAID')
    count_paid = len([tx for tx in transactions if tx.get('status') == 'PAID'])

    # Ambil daftar voucher dari Firestore
    vouchers_ref = db_fs.collection("Photobox").document(booth_id).collection("Vouchers")
    vouchers = []
    for doc in vouchers_ref.stream():
        v = doc.to_dict()
        v["id"] = doc.id
        vouchers.append(v)

    return render_template("dashboard.html",
        total_paid=total_paid,
        count_paid=count_paid,
        config=config,
        price_per_session=config.get("price"),
        username=session.get("admin_username"),
        doc_id=booth_id,
        vouchers=vouchers  # 🆕 pass ke template
    )


@dashboard_bp.route("/admin_update", methods=["POST"])
def admin_update():
    if not session.get("admin_logged_in"):
        return redirect("/login")
    activation_id = session.get("activation_id") or session.get("booth_id")
    data = {
        "price": int(request.form.get("price_per_session", 10000)),
        "xendit_api_key": request.form.get("xendit_api_key", ""),
        "callback_url": request.form.get("callback_url", ""),
        "dslrbooth_api_url": request.form.get("dslrbooth_api_url", ""),
        "dslrbooth_api_password": request.form.get("dslrbooth_api_password", "")
    }
    db_fs.collection("Photobox").document(activation_id).set(data, merge=True)
    return redirect("/dashboard")

@dashboard_bp.route("/manage_users", methods=["GET", "POST"])
def manage_users():
    form = ManageUserForm()
    users_ref = db_fs.collection("Users")
    config_ref = db_fs.collection("Photobox")

    if form.validate_on_submit():
        new_id = db_fs.collection("Users").document().id
        user_data = {
            "username": form.username.data,
            "password": form.password.data,
            "booth_id": new_id
        }
        config_data = {
            "price": form.price.data,
            "xendit_api_key": form.xendit_api_key.data,
            "callback_url": form.callback_url.data,
            "dslrbooth_api_url": form.dslrbooth_api_url.data,
            "dslrbooth_api_password": form.dslrbooth_api_password.data
        }
        db_fs.collection("app_state").document(new_id).set({"is_activated": False})
        users_ref.document(new_id).set(user_data)
        config_ref.document(new_id).set(config_data)
        flash("User berhasil ditambahkan!", "success")
        return redirect("/manage_users")

    users = []
    for doc in users_ref.stream():
        user = doc.to_dict()
        user["id"] = doc.id
        config = config_ref.document(doc.id).get()
        if config.exists:
            user.update(config.to_dict())
        users.append(user)

    return render_template("manage_users.html", users=users, form=form)

@dashboard_bp.route("/add_activation", methods=["POST"])
def add_activation():
    if not session.get("admin_logged_in"):
        return redirect("/login")

    doc_id = request.form.get("doc_id")
    data = {
        "username": request.form.get("username"),
        "password": request.form.get("password"),
        "price": int(request.form.get("price", 10000)),
        "xendit_api_key": request.form.get("xendit_api_key"),
        "callback_url": request.form.get("callback_url"),
        "dslrbooth_api_url": request.form.get("dslrbooth_api_url"),
        "dslrbooth_api_password": request.form.get("dslrbooth_api_password")
    }

    db_fs.collection("Photobox").document(doc_id).set(data)
    flash("Data baru berhasil ditambahkan!", "success")
    return redirect("/manage_users")

@dashboard_bp.route("/add_voucher", methods=["POST"])
def add_voucher():
    booth_id = session.get("booth_id")
    if not booth_id:
        return redirect("/login")

    code = request.form.get("voucher_code", "").upper()
    price = int(request.form.get("voucher_price", 0))
    active = request.form.get("voucher_active") == "on"

    db_fs.collection("Photobox").document(booth_id) \
        .collection("Vouchers").document(code).set({
            "price": price,
            "active": active
        })

    flash("Voucher berhasil ditambahkan!", "success")
    return redirect("/dashboard")

@dashboard_bp.route("/delete_voucher", methods=["POST"])
def delete_voucher():
    booth_id = session.get("booth_id")
    code = request.form.get("voucher_code", "").upper()

    db_fs.collection("Photobox").document(booth_id) \
        .collection("Vouchers").document(code).delete()

    flash("Voucher berhasil dihapus!", "success")
    return redirect("/dashboard")

@dashboard_bp.route("/update_voucher", methods=["POST"])
def update_voucher():
    if not session.get("admin_logged_in"):
        return redirect("/login")

    activation_id = session.get("booth_id")
    code = request.form.get("voucher_code")
    price = int(request.form.get("voucher_price", 10000))
    active = request.form.get("voucher_active") == "true"

    voucher_ref = db_fs.collection("Photobox").document(activation_id).collection("Vouchers").document(code)
    voucher_ref.set({"price": price, "active": active}, merge=True)

    flash(f"Voucher {code} berhasil diperbarui.", "success")
    return redirect("/dashboard")
