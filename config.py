from pathlib import Path
import os

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env", override=True)


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "interviewforge-secret-key")
    DEBUG = os.environ.get("FLASK_DEBUG", "1") == "1"
    TEMPLATES_AUTO_RELOAD = True
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        "mysql+pymysql://root:StrongPass123%21@localhost/interviewforge",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 280,
    }
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
    PRIMARY_LLM_MODEL = os.environ.get("PRIMARY_LLM_MODEL", "claude-3-7-sonnet-latest")
    XAI_API_KEY = os.environ.get("XAI_API_KEY", "")
    SECONDARY_LLM_MODEL = os.environ.get("SECONDARY_LLM_MODEL", "grok-3-mini")
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
    OPENAI_STT_MODEL = os.environ.get("OPENAI_STT_MODEL", "gpt-4o-mini-transcribe")
    OPENAI_TTS_MODEL = os.environ.get("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
    OPENAI_TTS_VOICE = os.environ.get("OPENAI_TTS_VOICE", "alloy")
    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", "uploads")
    REPORT_FOLDER = os.environ.get("REPORT_FOLDER", "reports")
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH", str(16 * 1024 * 1024)))
    DEFAULT_DIFFICULTY = os.environ.get("DEFAULT_DIFFICULTY", "medium")
    MAX_QUESTIONS = int(os.environ.get("MAX_QUESTIONS", "10"))
    PASS_SCORE_THRESHOLD = int(os.environ.get("PASS_SCORE_THRESHOLD", "7"))
    REMEMBER_COOKIE_HTTPONLY = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
