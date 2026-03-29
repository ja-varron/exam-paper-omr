from flask import Flask
from flask_cors import CORS

from .config import Settings
from .extensions import db
from .models import ExamResult
from .routes.accounts import accounts_bp
from .routes.auth import auth_bp
from .routes.exams import exams_bp
from .routes.health import health_bp


def create_app(settings: Settings | None = None) -> Flask:
    app = Flask(__name__)

    cfg = settings or Settings.from_env()
    app.config.from_mapping(
        DEBUG=cfg.debug,
        SECRET_KEY=cfg.secret_key,
        MAX_CONTENT_LENGTH=cfg.max_content_length,
        SQLALCHEMY_DATABASE_URI=cfg.database_url,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SUPABASE_URL=cfg.supabase_url,
        SUPABASE_SERVICE_ROLE_KEY=cfg.supabase_service_role_key,
        AUTH_REQUIRED=cfg.auth_required,
    )

    # In local development, frontend dev servers may rotate ports (5173, 5174, ...).
    # Allow all origins for /api routes to prevent CORS blocks while iterating.
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    db.init_app(app)
    with app.app_context():
        db.create_all()

    app.register_blueprint(health_bp, url_prefix="/api")
    app.register_blueprint(auth_bp, url_prefix="/api")
    app.register_blueprint(accounts_bp, url_prefix="/api")
    app.register_blueprint(exams_bp, url_prefix="/api")

    return app
