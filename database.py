import os

from dotenv import load_dotenv
from sqlalchemy.engine import URL
from sqlmodel import Session, create_engine

load_dotenv()

REQUIRED = ["DB_USER", "DB_PASSWORD", "DB_HOST", "DB_PORT", "DB_NAME"]
missing = [name for name in REQUIRED if not os.getenv(name)]
if missing:
    raise RuntimeError(f"Missing in backend/.env: {', '.join(missing)}")

DATABASE_URL = URL.create(
    drivername="postgresql+psycopg2",
    username=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    host=os.getenv("DB_HOST"),
    port=int(os.getenv("DB_PORT")),
    database=os.getenv("DB_NAME"),
    query={"sslmode": "require"},
)

# Supabase's session pooler allows only a limited number of connections, so the
# pool is kept small and can be tuned per environment.
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=int(os.getenv("DB_POOL_SIZE", "5")),
    max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "5")),
    pool_recycle=1800,
)


def get_session():
    with Session(engine) as session:
        yield session