from __future__ import annotations

"""
app.py: Flask entry point - sets up CORS, serves the frontend, and registers all API routes.
"""

import logging
import os
import sys

from flask import Flask, request, jsonify, send_from_directory

from routes.protein_routes import protein_bp

# I use the absolute path so the server finds the frontend regardless of which directory you run it from.
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend")

# Logging is configured here once so every module in the app uses the same format automatically.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)

logger = logging.getLogger(__name__)


def create_app() -> Flask:
    """Create and configure the Flask app - I use a factory so tests and the server both go through the same setup."""
    app = Flask(__name__)
    app.register_blueprint(protein_bp)

    # Manual CORS: handle OPTIONS preflight before routes, then add headers
    # to every response via after_request.
    @app.before_request
    def handle_preflight():
        if request.method == "OPTIONS":
            resp = jsonify({})
            resp.headers["Access-Control-Allow-Origin"] = "*"
            resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
            return resp, 204

    @app.after_request
    def add_cors_headers(response):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return response

    # Serve the frontend from the same Flask process so you just run
    # python app.py and open http://127.0.0.1:5000.
    @app.route("/")
    def index():
        return send_from_directory(FRONTEND_DIR, "index.html")

    @app.route("/<path:filename>")
    def frontend_static(filename):
        return send_from_directory(FRONTEND_DIR, filename)

    logger.info("ProteinVis application created, routes registered")
    logger.info("Frontend served from: %s", os.path.abspath(FRONTEND_DIR))
    return app


app = create_app()

if __name__ == "__main__":
    logger.info("Starting ProteinVis dev server at http://127.0.0.1:5000")
    app.run(debug=True, port=5000, host="127.0.0.1")
