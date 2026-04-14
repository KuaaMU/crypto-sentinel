"""
Crypto Sentinel Dashboard - Flask web application.

Run standalone: python -m src.dashboard.app
"""
import os
from pathlib import Path

from flask import Flask


def create_app() -> Flask:
    """Flask application factory."""
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).parent / "templates"),
        static_folder=str(Path(__file__).parent / "static"),
    )
    app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "sentinel-dev-key")

    # Register blueprints
    from src.dashboard.views import views_bp
    from src.dashboard.api import api_bp

    app.register_blueprint(views_bp)
    app.register_blueprint(api_bp, url_prefix="/api")

    return app


# For standalone running
if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=True)
