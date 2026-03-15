import os
from dataclasses import dataclass


@dataclass(slots=True)
class Settings:
    debug: bool
    secret_key: str
    max_content_length: int
    allowed_origins: list[str]
    database_url: str

    @classmethod
    def from_env(cls) -> "Settings":
        debug = os.getenv("FLASK_DEBUG", "0") == "1"
        secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-key")
        max_content_length = int(os.getenv("MAX_CONTENT_LENGTH", str(10 * 1024 * 1024)))
        origins_raw = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
        allowed_origins = [origin.strip() for origin in origins_raw.split(",") if origin.strip()]
        database_url = os.getenv("DATABASE_URL", "sqlite:///exam_omr.db")

        return cls(
            debug=debug,
            secret_key=secret_key,
            max_content_length=max_content_length,
            allowed_origins=allowed_origins,
            database_url=database_url,
        )
