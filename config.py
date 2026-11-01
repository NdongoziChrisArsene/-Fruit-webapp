"""Reads settings from environment variables, then from Streamlit secrets."""
import os


def get(name: str, default=None):
    value = os.environ.get(name)
    if value not in (None, ""):
        return value
    try:
        import streamlit as st

        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass
    return default


def database_url() -> str:
    url = get("DATABASE_URL")
    if not url:
        user = get("POSTGRES_USER", "fruit")
        password = get("POSTGRES_PASSWORD", "")
        host = get("POSTGRES_HOST", "localhost")
        port = get("POSTGRES_PORT", "5432")
        name = get("POSTGRES_DB", "fruitdb")
        url = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{name}"
    # Hosting providers often give "postgres://" or "postgresql://"
    if url.startswith("postgres://"):
        url = "postgresql+psycopg2://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg2://" + url[len("postgresql://"):]
    return url


MODEL_PATH = get("MODEL_PATH", "models/best.pt")
CONFIDENCE_THRESHOLD = float(get("CONFIDENCE_THRESHOLD", "0.60"))
STORE_IMAGES = str(get("STORE_IMAGES", "true")).lower() in ("1", "true", "yes")
MAX_LOGIN_ATTEMPTS = int(get("MAX_LOGIN_ATTEMPTS", "5"))
LOCKOUT_MINUTES = int(get("LOCKOUT_MINUTES", "15"))
