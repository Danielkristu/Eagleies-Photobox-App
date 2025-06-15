from .auth import auth_bp
from .dashboard import dashboard_bp
from .client import client_bp
from .payment import payment_bp
from routes.voucher import voucher_bp

def register_routes(app):
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(client_bp)
    app.register_blueprint(payment_bp)
    app.register_blueprint(voucher_bp)
