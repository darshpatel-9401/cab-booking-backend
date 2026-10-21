import os

from dotenv import load_dotenv

load_dotenv()

DEFAULT_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000"


def parse_origins(raw: str) -> list:
    origins = [item.strip().rstrip("/") for item in raw.split(",") if item.strip()]
    if "*" in origins:
        raise RuntimeError("ALLOWED_ORIGINS must list exact origins, not *")
    return origins


ALLOWED_ORIGINS = parse_origins(os.getenv("ALLOWED_ORIGINS", DEFAULT_ORIGINS))
ENABLE_DOCS = os.getenv("ENABLE_DOCS", "true").lower() == "true"