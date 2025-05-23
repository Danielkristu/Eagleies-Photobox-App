from flask import Blueprint, render_template, redirect, session, request, jsonify, flash
from utils.helpers import db_fs
import time
import pyautogui

client_bp = Blueprint("client", __name__)

photobooth_session_state = "running"




@client_bp.route("/<doc_id>")
def photobox_home(doc_id):
    doc = db_fs.collection("Photobox").document(doc_id).get()
    if not doc.exists:
        flash("Activation code tidak ditemukan.", "error")
        return redirect("/activate")

    app_state = db_fs.collection("app_state").document(doc_id).get()
    if not app_state.exists or not app_state.to_dict().get("is_activated", False):
        flash("Aplikasi belum diaktivasi.", "error")
        return redirect("/activate")

    session["activation_id"] = doc_id
    return render_template("index.html", doc_id=doc_id)


@client_bp.route("/<doc_id>/session_end")
def session_end(doc_id):
    global photobooth_session_state
    event_type = request.args.get("event_type")
    session["activation_id"] = doc_id

    if event_type and event_type.strip().lower() == "session_end":
        photobooth_session_state = f"ended:{doc_id}"
        try:
            time.sleep(0.5)
            pyautogui.hotkey("alt", "tab")
        except Exception as e:
            print("❌ Gagal Alt+Tab:", e)

        doc = db_fs.collection("Photobox").document(doc_id).get()
        if not doc.exists:
            return "Data tidak ditemukan", 404
        return render_template("index.html", doc_id=doc_id)

    return f"Event tidak ditangani: {event_type}", 200


@client_bp.route("/<doc_id>/check_session_state")
def check_session_state(doc_id):
    global photobooth_session_state
    if photobooth_session_state == f"ended:{doc_id}":
        return jsonify({"state": "ended"})
    return jsonify({"state": "running"})
