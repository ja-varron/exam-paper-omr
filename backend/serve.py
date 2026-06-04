from __future__ import annotations

import os

from waitress import serve

from app import create_app

app = create_app()


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "5000"))

    # Sensible defaults for small deployments. Override via env vars if traffic grows.
    threads = int(os.getenv("WAITRESS_THREADS", "4"))
    connection_limit = int(os.getenv("WAITRESS_CONNECTION_LIMIT", "200"))
    channel_timeout = int(os.getenv("WAITRESS_CHANNEL_TIMEOUT", "60"))

    serve(
        app,
        host=host,
        port=port,
        threads=threads,
        connection_limit=connection_limit,
        channel_timeout=channel_timeout,
    )
