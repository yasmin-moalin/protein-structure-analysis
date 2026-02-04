from __future__ import annotations

"""
app.py — Flask application entry point

I use a create_app() factory rather than a module-level Flask instance
because the factory pattern makes the app testable — a test suite can call
create_app() to spin up a fresh instance without starting the server.

CORS is implemented manually via an after_request hook rather than flask-cors.
The manual approach means I understand exactly which headers are being set and
why. This is a tool aimed at students and researchers who might inspect the
network traffic, so being explicit about the CORS policy is good practice.
The Access-Control-Allow-Origin: * is safe here because this API serves only
read-only public data (PDB and AlphaFold files are both openly licensed) and
there are no session cookies or credentials involved.

I run on port 5000 by default, which avoids the macOS AirPlay conflict on 5000
— actually macOS uses 5000 for AirPlay but Windows doesn't, so 5000 is fine
here. I set it explicitly so it's obvious and not reliant on Flask's default.
"""

import logging
import os
import sys

from flask import Flask, request, jsonify, send_from_directory

from routes.protein_routes import protein_bp

# The frontend files live one directory up from the backend, so I compute
# the absolute path here rather than using a relative path — relative paths
# are resolved from the working directory, which breaks if someone runs
# app.py from a different directory than backend/.
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend")

# I configure structured logging at the app level so the format is consistent
# across all modules. Each logger in fetcher.py, service.py etc. inherits
# this configuration automatically via Python's logger hierarchy.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)

logger = logging.getLogger(__name__)


def create_app() -> Flask:
    """
    Create and configure the Flask application.

    Keeping this as a factory function (rather than module-level setup)
    means tests and the __main__ block both use the same code path, which
    prevents the 'works in dev, fails in test' class of bugs.
    """
    app = Flask(__name__)
    app.register_blueprint(protein_bp)

    # Manual CORS — I handle preflight OPTIONS requests before they hit any
    # route, then add the CORS headers to every actual response via
    # after_request. This is simpler than it looks: OPTIONS is just a browser
    # asking 'are you allowed to respond to this domain?', and the answer
    # here is always yes because the frontend and backend run on the same
    # machine with no credentials at stake.
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

    # Serve the frontend — this is the simplest way to get everything running
    # from a single URL. Flask serves index.html at / and any other static
    # files (styles.css, main.js) at their natural paths. This means the user
    # only needs to run `python app.py` and open http://127.0.0.1:5000 —
    # no separate static server required.
    @app.route("/")
    def index():
        return send_from_directory(FRONTEND_DIR, "index.html")

    @app.route("/<path:filename>")
    def frontend_static(filename):
        return send_from_directory(FRONTEND_DIR, filename)

    logger.info("ProteinVis application created — routes registered")
    logger.info("Frontend served from: %s", os.path.abspath(FRONTEND_DIR))
    return app


app = create_app()

if __name__ == "__main__":
    logger.info("Starting ProteinVis dev server at http://127.0.0.1:5000")
    app.run(debug=True, port=5000, host="127.0.0.1")
