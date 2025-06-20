# app.py
import os
import threading
import time
import sys
from functools import wraps

from flask import (
    Flask, render_template, redirect, request, session, flash, url_for, Blueprint
)
from flask_cors import CORS
from google.cloud import firestore
from datetime import timedelta
from dotenv import load_dotenv
from routes import register_routes
import waitress

from routes.auth import auth_bp
from routes.dashboard import dashboard_bp
from routes.client import client_bp
from routes.payment import payment_bp
from routes.voucher import voucher_bp
# --- Initialization ---

# Load environment variables from a .env file
load_dotenv()

# Set GOOGLE_APPLICATION_CREDENTIALS for PyInstaller (exe) and normal run
base_dir = getattr(sys, '_MEIPASS', os.path.abspath(os.path.dirname(__file__)))
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.path.join(base_dir, "serviceAccountKey.json")

# Initialize Flask app
app = Flask(__name__)
# It's crucial to set a strong, secret key for session security
app.config['SECRET_KEY'] = os.getenv("SECRET_KEY", "a-very-secret-key-that-is-long-and-random")
app.config['SESSION_COOKIE_HTTPONLY'] = True  # Prevents client-side script access to the cookie
app.config['SESSION_COOKIE_SECURE'] = False    # Set to True if your app is served over HTTPS
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
# Set session to last for a week, suitable for a photobooth environment
app.permanent_session_lifetime = timedelta(days=7) 
CORS(app)
app.register_blueprint(payment_bp)
app.register_blueprint(client_bp)
app.register_blueprint(voucher_bp)
# --- Firestore Setup ---
# This uses Application Default Credentials.
# Ensure the GOOGLE_APPLICATION_CREDENTIALS environment variable is set in your .env file
# and points to your serviceAccountKey.json file.
# Example .env file line:
# GOOGLE_APPLICATION_CREDENTIALS="path/to/your/serviceAccountKey.json"
try:
    db_fs = firestore.Client()
    print("Successfully connected to Firestore.")
except Exception as e:
    print(f"Error connecting to Firestore: {e}")
    db_fs = None


# --- Authentication Blueprint ---
# Organizes login-related routes into a logical group named 'auth'
auth_bp = Blueprint('auth', __name__)

@auth_bp.route("/sign")
def sign():
    """Renders the login page ('signin.html'). If a session already exists,
    it redirects directly to the main booth page."""
    if 'booth_id' in session:
        return redirect(url_for('start_page'))
    return render_template("signin.html")

@auth_bp.route("/login", methods=["POST"])
def login():
    """Handles the login form submission from the /sign page."""
    if not db_fs:
        flash("Database connection is not available.", "error")
        return redirect(url_for('auth.sign'))

    booth_code = request.form.get("boothCode")
    if not booth_code:
        flash("Booth Code is required.", "error")
        return redirect(url_for('auth.sign'))

    try:
        # This is an efficient 'collection group' query. It searches across all
        # 'Booths' subcollections in your database for a document with the matching code.
        booths_ref = db_fs.collection_group('Booths').where('boothCode', '==', booth_code).limit(1)
        docs = list(booths_ref.stream())

        if docs:
            booth_doc = docs[0]
            booth_id = booth_doc.id
            # The client ID is the ID of the parent document of the 'Booths' subcollection.
            client_id = booth_doc.reference.parent.parent.id

            # Store the necessary IDs in the session to track the logged-in state.
            session.permanent = True  # Make the session last for the configured duration.
            session['client_id'] = client_id
            session['booth_id'] = booth_id
            
            print(f"Login successful for Booth Code: {booth_code}. ClientID: {client_id}, BoothID: {booth_id}")
            
            return redirect(url_for('start_page', booth_id=booth_id))
        else:
            flash("Invalid Booth Code. Please try again.", "error")
            return redirect(url_for('auth.sign'))

    except Exception as e:
        flash(f"An error occurred during login: {e}", "error")
        print(f"Error during login: {e}")
        return redirect(url_for('auth.sign'))

@auth_bp.route("/")
def booth():
    """
    Displays the main photobooth page after successful login.
    This route is protected; it redirects to the sign-in page if no session is found.
    This is the correct place to render your main application page (index.html).
    """
    if 'booth_id' not in session or 'client_id' not in session:
        flash("You must be logged in to view this page.", "error")
        return redirect(url_for('auth.sign'))
    # Get the booth_id and client_id from the session to pass to the template
    doc_id = session.get('booth_id')
    client_id = session.get('client_id')
    bg_url = None
    try:
        if client_id and doc_id:
            doc = db_fs.collection('Clients').document(client_id) \
                .collection('Booths').document(doc_id) \
                .collection('backgrounds').document('startBg').get()
            if doc.exists:
                bg_url = doc.to_dict().get('url')
    except Exception as e:
        print(f"Error fetching background URL for index: {e}")
    return render_template("index.html", doc_id=doc_id, bg_url=bg_url)


@auth_bp.route("/logout")
def logout():
    """Clears the session to log the user out and redirects to the sign-in page."""
    session.clear()
    flash("You have been successfully logged out.", "info")
    return redirect(url_for('auth.sign'))

# Register the blueprints with the main Flask app
app.register_blueprint(auth_bp)


# --- Main Application Route ---

@app.route("/")
def home():
    """
    The main entry point of the app.
    If accessed without a booth_id, redirect to the access code page.
    """
    # If someone tries to access '/', always redirect to access code page
    return redirect(url_for('auth.sign'))

def check_activation(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        booth_id = kwargs.get('booth_id')
        # Only allow access if booth_id is present and matches session
        if not booth_id or session.get('booth_id') != booth_id:
            flash('Akses tidak diizinkan. Silakan login dengan kode booth yang benar.', 'error')
            return redirect(url_for('auth.sign'))
        return f(*args, **kwargs)
    return decorated_function

# Example usage for index page:
@app.route('/<booth_id>')
@check_activation
def booth_index(booth_id):
    client_id = session.get('client_id')
    bg_url = None
    # Check if the booth exists in Firestore for this client
    booth_exists = False
    try:
        if client_id and booth_id:
            booth_ref = db_fs.collection('Clients').document(client_id).collection('Booths').document(booth_id)
            if booth_ref.get().exists:
                booth_exists = True
                doc = booth_ref.collection('backgrounds').document('startBg').get()
                if doc.exists:
                    bg_url = doc.to_dict().get('url')
    except Exception as e:
        print(f"Error fetching background URL for index: {e}")
    if not booth_exists:
        flash('Booth tidak ditemukan. Silakan masukkan kode akses.', 'error')
        return redirect(url_for('auth.sign'))
    return render_template('index.html', doc_id=booth_id, booth_id=booth_id, bg_url=bg_url)

# Update your /start/<booth_id> route to also require activation
@app.route("/start/<booth_id>")
@check_activation
def start_page(booth_id):
    bg_url = None
    client_id = session.get('client_id')
    booth_exists = False
    try:
        if client_id and booth_id:
            booth_ref = db_fs.collection('Clients').document(client_id).collection('Booths').document(booth_id)
            if booth_ref.get().exists:
                booth_exists = True
                doc = booth_ref.collection('backgrounds').document('homeBg').get()
                if doc.exists:
                    bg_url = doc.to_dict().get('url')
    except Exception as e:
        print(f"Error fetching background URL: {e}")
    if not booth_exists:
        flash('Booth tidak ditemukan. Silakan masukkan kode akses.', 'error')
        return redirect(url_for('auth.sign'))
    return render_template("StartPage.html", bg_url=bg_url, booth_id=booth_id)


# --- Webview and Flask Server ---
# The following code is for running Flask within a PyWebview desktop window.

def start_flask():
    """Function to run the Flask app."""
    # use_reloader=False is important to prevent issues when running in a thread.
    # waitress.serve will not show the Flask dev server warning and is production-ready
    waitress.serve(app, host='127.0.0.1', port=5000)

if __name__ == "__main__":
    # Only use webview if running locally (not in Cloud Run)
    try:
        import webview
        # Run Flask in a separate thread so it doesn't block the GUI thread.
        flask_thread = threading.Thread(target=start_flask, daemon=True)
        flask_thread.start()

        # Wait a moment for Flask to start up before opening the window.
        time.sleep(1)

        # Create and start the PyWebview desktop window pointing to the Flask server.
        webview.create_window(
            "Eagleies Photobox",
            url="http://127.0.0.1:5000/",
            width=1280,
            height=800
        )
        webview.start()
    except ImportError:
        # If webview is not available, just run Flask normally (for Cloud Run)
        port = int(os.environ.get("PORT", 8080))
        app.run(host="0.0.0.0", port=port)