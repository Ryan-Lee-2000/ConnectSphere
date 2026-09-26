import os
from pathlib import Path

import httpx
from dotenv import load_dotenv
from flask import Flask, abort, g, jsonify, request, send_from_directory
from sqlalchemy import create_engine, text

from .authorization import associate_account_roles, authenticated_only
from .coordinator_assignment import register_coordinator_assignment_routes
from .event_requests import register_event_request_routes
from .event_review import register_event_review_routes
from .venue_operational_blocks import register_venue_operational_block_routes
from .venues import register_venue_routes


def create_app(test_config=None):
    load_dotenv()
    static = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    app = Flask(__name__, static_folder=None)
    app.config.from_mapping(
        DATABASE_URL=os.getenv("DATABASE_URL"),
        SUPABASE_URL=os.getenv("SUPABASE_URL", ""),
        SUPABASE_PUBLISHABLE_KEY=os.getenv("SUPABASE_PUBLISHABLE_KEY", ""),
        MAX_CONTENT_LENGTH=16_384,
    )
    if test_config:
        app.config.update(test_config)
    if not app.config["DATABASE_URL"]:
        raise RuntimeError("DATABASE_URL missing. Run npm run setup; see .env.example.")
    engine = create_engine(app.config["DATABASE_URL"], pool_pre_ping=True)
    app.extensions["engine"] = engine

    @app.before_request
    def identity():
        if not request.path.startswith("/api/") or request.path == "/api/health":
            return
        token = request.headers.get("Authorization", "")
        if not token.startswith("Bearer ") or not token[7:].strip():
            abort(401, "Sign in to continue.")
        # Test verifier injection exists only through create_app's explicit test configuration.
        if app.testing and "IDENTITY_VERIFIER" in app.config:
            g.user_id = app.config["IDENTITY_VERIFIER"](token[7:])
        else:
            try:
                response = httpx.get(
                    app.config["SUPABASE_URL"].rstrip("/") + "/auth/v1/user",
                    headers={
                        "Authorization": token,
                        "apikey": app.config["SUPABASE_PUBLISHABLE_KEY"],
                    },
                    timeout=5,
                )
            except httpx.RequestError:
                abort(503, "Authentication service unavailable.")
            if response.status_code in (401, 403):
                abort(401, "Session expired or invalid.")
            if response.status_code != 200:
                abort(503, "Authentication service unavailable.")
            g.user_id = response.json().get("id")
        if not g.user_id:
            abort(401)
        associate_account_roles(engine, app.view_functions.get(request.endpoint))

    @app.errorhandler(400)
    @app.errorhandler(401)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(409)
    @app.errorhandler(413)
    @app.errorhandler(503)
    def error_response(error):
        return jsonify(error=error.description), error.code

    @app.get("/api/health")
    def health():
        try:
            with engine.connect() as conn:
                conn.execute(text("select 1"))
        except Exception:
            return jsonify(status="unavailable"), 503
        return jsonify(
            status="ok", commit=os.getenv("RENDER_GIT_COMMIT", os.getenv("RELEASE_COMMIT", "local"))
        )

    @app.get("/api/session")
    @authenticated_only
    def session_identity():
        # Infrastructure probe only: authentication does not grant business permissions.
        return jsonify(user_id=g.user_id)

    @app.get("/api/account/roles")
    @authenticated_only
    def current_account_roles():
        return jsonify(roles=sorted(g.account_roles))

    register_venue_routes(app)
    register_venue_operational_block_routes(app)
    register_event_request_routes(app)
    register_coordinator_assignment_routes(app)
    register_event_review_routes(app)

    @app.get("/")
    @app.get("/<path:path>")
    def frontend(path="index.html"):
        if path.startswith("api/"):
            abort(404)
        if (static / path).is_file():
            return send_from_directory(static, path)
        if (static / "index.html").is_file():
            return send_from_directory(static, "index.html")
        abort(404, "Start the Vite frontend with npm start.")

    return app
