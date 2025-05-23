import firebase_admin
from firebase_admin import app_check
import flask
import jwt

firebase_app = firebase_admin.initialize_app()
flask_app = flask.Flask(__name__)

@flask_app.before_request
def verify_app_check() -> None:
    app_check_token = flask.request.headers.get("X-Firebase-AppCheck", default="")
    try:
        app_check_claims = app_check.verify_token(app_check_token)
        # If verify_token() succeeds, okay to continue to route handler.
    except (ValueError, jwt.exceptions.DecodeError):
        flask.abort(401)
