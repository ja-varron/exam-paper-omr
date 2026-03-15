from flask import Flask
from flask_cors import CORS

from .config import Settings
from .extensions import db
from .models import ExamResult
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
    )

    CORS(app, resources={r"/api/*": {"origins": cfg.allowed_origins}})

    db.init_app(app)
    with app.app_context():
        db.create_all()

    app.register_blueprint(health_bp, url_prefix="/api")
    app.register_blueprint(exams_bp, url_prefix="/api")

    return app
