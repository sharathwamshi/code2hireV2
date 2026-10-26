import logging
import os

from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS

from config import Config
from extensions import db


def create_app(config_overrides=None):
    static_dir = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
    app = Flask(__name__, static_folder=static_dir, static_url_path="/")
    app.config.from_object(Config)
    if config_overrides:
        app.config.update(config_overrides)
    os.makedirs(app.config["UPLOAD_DIR"], exist_ok=True)
    logging.basicConfig(level=logging.INFO)

    db.init_app(app)
    CORS(app, resources={r"/api/*": {"origins": app.config["CORS_ORIGINS"].split(",")}})

    from routes.auth import bp as auth_bp
    from routes.platform import bp as platform_bp
    from routes.company import bp as company_bp
    from routes.jobs import bp as jobs_bp
    from routes.rounds import bp as rounds_bp
    from routes.isha import bp as isha_bp
    from routes.reports import bp as reports_bp
    from routes.candidate import bp as candidate_bp
    from routes.certs import bp as certs_bp
    from routes.inbox import bp as inbox_bp
    from routes.public import bp as public_bp
    from routes.speech import bp as speech_bp
    from routes.call import bp as call_bp
    for bp in (auth_bp, platform_bp, company_bp, jobs_bp, rounds_bp, isha_bp, reports_bp, candidate_bp,
               certs_bp, inbox_bp, public_bp, speech_bp, call_bp):
        app.register_blueprint(bp)

    @app.get("/api/health")
    def health():
        from services import ai, speech
        return jsonify({"ok": True, "anthropic": ai.configured(), "azure_speech": speech.configured()})

    @app.errorhandler(404)
    def not_found(e):
        from flask import request
        if request.path.startswith("/api/"):
            return jsonify({"error": "Not found"}), 404
        index = os.path.join(static_dir, "index.html")
        if os.path.exists(index):
            return send_from_directory(static_dir, "index.html")
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(500)
    def server_error(e):
        db.session.rollback()
        return jsonify({"error": "Something went wrong on our side. Please try again."}), 500

    with app.app_context():
        db.create_all()
    return app


app = create_app() if os.getenv("C2H_NO_AUTOCREATE") != "1" else None

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5050")), debug=os.getenv("FLASK_DEBUG") == "1")
