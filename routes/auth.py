from flask import Blueprint, render_template, redirect, session, request, flash
from google.cloud.firestore_v1 import FieldFilter
from forms.forms import LoginForm
from utils.helpers import db_fs

auth_bp = Blueprint("auth", __name__)

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        username = form.username.data
        password = form.password.data

        users = db_fs.collection("Users") \
            .where(filter=FieldFilter("username", "==", username)) \
            .where(filter=FieldFilter("password", "==", password)) \
            .stream()

        user = next(users, None)

        if user:
            user_data = user.to_dict()
            session["admin_logged_in"] = True
            session["booth_id"] = user_data.get("booth_id")
            return redirect("/dashboard")

        flash("Username atau Password salah", "error")
    return render_template("login.html", form=form)

@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect("/login")
