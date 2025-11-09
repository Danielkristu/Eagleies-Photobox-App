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

import logging
from routes.auth import auth_bp
from routes.dashboard import dashboard_bp
from routes.client import client_bp
from routes.payment import payment_bp
from routes.voucher import voucher_bp

# --- Initialization ---

# Set up logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# Load environment variables from a .env file
load_dotenv()

# Set GOOGLE_APPLICATION_CREDENTIALS for PyInstaller (exe) and normal run
if hasattr(sys, '_MEIPASS'):
    base_dir = sys._MEIPASS
else:
    base_dir = os.path.abspath(os.path.dirname(__file__))
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.path.join(base_dir, "serviceAccountKey.json")

# Initialize Flask app
app = Flask(__name__)

app.config['SECRET_KEY'] = os.getenv("SECRET_KEY", "a-very-secret-key-that-is-long-and-random")
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SECURE'] = False
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.permanent_session_lifetime = timedelta(days=7) 
CORS(app)
app.register_blueprint(payment_bp)
app.register_blueprint(client_bp)
app.register_blueprint(voucher_bp)

# --- Firestore Setup ---
try:
    db_fs = firestore.Client()
    print("Successfully connected to Firestore.")
except Exception as e:
    print(f"Error connecting to Firestore: {e}")
    db_fs = None


# --- Authentication Blueprint ---
auth_bp = Blueprint('auth', __name__)

@auth_bp.route("/sign")
def sign():
    if 'booth_id' in session:
        return redirect(url_for('start_page'))
    return render_template("signin.html")

@auth_bp.route("/login", methods=["POST"])
def login():
    if not db_fs:
        flash("Database connection is not available.", "error")
        return redirect(url_for('auth.sign'))

    booth_code = request.form.get("boothCode")
    if not booth_code:
        flash("Booth Code is required.", "error")
        return redirect(url_for('auth.sign'))

    try:
        booths_ref = db_fs.collection_group('Booths').where('boothCode', '==', booth_code).limit(1)
        docs = list(booths_ref.stream())

        if docs:
            booth_doc = docs[0]
            booth_id = booth_doc.id
            client_id = booth_doc.reference.parent.parent.id

            session.permanent = True
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
    if 'booth_id' not in session or 'client_id' not in session:
        flash("You must be logged in to view this page.", "error")
        return redirect(url_for('auth.sign'))
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
    session.clear()
    flash("You have been successfully logged out.", "info")
    return redirect(url_for('auth.sign'))

app.register_blueprint(auth_bp)


# --- Main Application Route ---

@app.route("/")
def home():
    return redirect(url_for('auth.sign'))

def check_activation(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        booth_id = kwargs.get('booth_id')
        if not booth_id or session.get('booth_id') != booth_id:
            flash('Akses tidak diizinkan. Silakan login dengan kode booth yang benar.', 'error')
            return redirect(url_for('auth.sign'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/<booth_id>')
@check_activation
def booth_index(booth_id):
    client_id = session.get('client_id')
    bg_url = None
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


# --- PyQt6 and Flask Server ---

def start_flask():
    """Function to run the Flask app using waitress."""
    waitress.serve(app, host='127.0.0.1', port=5000)

def run_with_pyqt():
    """Run the application with PyQt6 GUI."""
    try:
        from PyQt6.QtWidgets import QApplication, QMainWindow
        from PyQt6.QtWebEngineWidgets import QWebEngineView
        from PyQt6.QtCore import QUrl, Qt
        from PyQt6.QtGui import QIcon
        
        class PhotoboothWindow(QMainWindow):
            def __init__(self):
                super().__init__()
                self.setWindowTitle("Eagleies Photobox")
                self.setGeometry(100, 100, 1280, 800)
                
                # Create the web view
                self.browser = QWebEngineView()
                self.browser.setUrl(QUrl("http://127.0.0.1:5000/"))
                
                # Set the web view as the central widget
                self.setCentralWidget(self.browser)
                
                # Optional: Enable developer tools (F12)
                self.browser.settings().setAttribute(
                    self.browser.settings().WebAttribute.JavascriptEnabled, True
                )
                
            def closeEvent(self, event):
                """Handle window close event."""
                event.accept()
        
        # Start Flask in a separate daemon thread
        flask_thread = threading.Thread(target=start_flask, daemon=True)
        flask_thread.start()
        
        # Wait for Flask to start
        time.sleep(1.5)
        
        # Create Qt Application
        qt_app = QApplication(sys.argv)
        qt_app.setApplicationName("Eagleies Photobox")
        
        # Create and show the main window
        window = PhotoboothWindow()
        window.show()
        
        # Start the Qt event loop
        sys.exit(qt_app.exec())
        
    except ImportError as e:
        logging.error(f"PyQt6 not available: {e}")
        logging.info("Please install PyQt6 and PyQt6-WebEngine:")
        logging.info("  pip install PyQt6 PyQt6-WebEngine")
        raise
    except Exception as e:
        logging.critical(f"Failed to create or start PyQt6 window: {e}")
        input("Press Enter to exit...")
        raise

if __name__ == "__main__":
    # Check if running in desktop mode or server mode
    if os.environ.get("RUN_MODE") == "server" or os.environ.get("PORT"):
        # Server mode (for Cloud Run or production)
        port = int(os.environ.get("PORT", 8080))
        app.run(host="0.0.0.0", port=port)
    else:
        # Desktop mode with PyQt6
        try:
            run_with_pyqt()
        except ImportError:
            logging.warning("PyQt6 not available, falling back to server mode")
            print("\nTo use desktop mode, install PyQt6:")
            print("  pip install PyQt6 PyQt6-WebEngine\n")
            # Fallback to simple Flask server
            port = int(os.environ.get("PORT", 5000))
            app.run(host="127.0.0.1", port=port, debug=True)