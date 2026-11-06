from dotenv import load_dotenv
load_dotenv()

import os
from datetime import timedelta


def _bool(v, default=False):
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")
    # MySQL in production, e.g. mysql+pymysql://user:pass@localhost:3306/code2hire?charset=utf8mb4
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL", "mysql+pymysql://code2hire:code2hire@localhost:3306/code2hire?charset=utf8mb4"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True, "pool_recycle": 280}
    TOKEN_TTL = timedelta(hours=int(os.getenv("TOKEN_TTL_HOURS", "12")))
    TRUST_PROXY = os.getenv("C2H_TRUST_PROXY", "1") != "0"  # behind nginx: read the client IP from X-Forwarded-For
    CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173")

    # Anthropic (all AI work). Can also be set from Platform settings in the UI.
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")

    # Azure Speech (all voice work). Can also be set from Platform settings in the UI.
    AZURE_SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY", "")
    AZURE_SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION", "centralindia")

    # Interview videos: private Azure Blob storage when set, else the server's disk (UPLOAD_DIR/recordings)
    AZURE_STORAGE_CONNECTION_STRING = os.getenv("C2H_AZURE_STORAGE_CONNECTION_STRING", "")
    AZURE_RECORDINGS_CONTAINER = os.getenv("C2H_AZURE_RECORDINGS_CONTAINER", "recordings")
    FFMPEG_BIN = os.getenv("C2H_FFMPEG", "ffmpeg")
    APP_VERSION = "V02.00.05"

    UPLOAD_DIR = os.getenv("UPLOAD_DIR", os.path.join(os.path.dirname(__file__), "uploads"))
    MAX_CONTENT_LENGTH = 200 * 1024 * 1024
    AI_FALLBACK = _bool(os.getenv("AI_FALLBACK", "true"), True)  # deterministic answers when no key is set
