from flask import Blueprint, render_template, request, redirect, session, flash
from forms.forms import ActivationForm
from utils.helpers import db_fs
from utils.helpers import get_device_mac


activate_bp = Blueprint("activate", __name__)

@activate_bp.route("/activate", methods=["GET", "POST"])
def activate():
    form = ActivationForm()

    if form.validate_on_submit():
        entered_code = form.activation_code.data
        config_doc = db_fs.collection("Photobox").document(entered_code).get()

        if config_doc.exists:
            mac_address = get_device_mac()
            session["activation_id"] = entered_code

            # Simpan ke Firestore dengan device MAC
            db_fs.collection("app_state").document(entered_code).set({
                "is_activated": True,
                "device_id": mac_address
            }, merge=True)

            return redirect(f"/{entered_code}")

        flash("Activation code tidak valid", "error")
        return redirect("/activate")

    return render_template("activation.html", form=form)