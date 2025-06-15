from flask import Blueprint, render_template, redirect, session, request, jsonify, flash
from utils.helpers import db_fs, download_and_replace_home_bg
import time
import pyautogui

client_bp = Blueprint("client", __name__)

photobooth_session_state = "running"




@client_bp.route("/<doc_id>")
def photobox_home(doc_id):
    

    session["activation_id"] = doc_id
    # Fetch homeBg from Firestore
    bg_url = None
    doc_bg = db_fs.collection('Photobox').document(doc_id).collection('backgrounds').document('homeBg').get()
    if doc_bg.exists:
        bg_url = doc_bg.to_dict().get('url')
        download_and_replace_home_bg(bg_url)
    local_bg_path = '/static/bg_cache/home_bg.jpg' if bg_url else ''
    import time
    cache_buster = int(time.time())
    return render_template("index.html", doc_id=doc_id, bg_url=local_bg_path, cache_buster=cache_buster)


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
