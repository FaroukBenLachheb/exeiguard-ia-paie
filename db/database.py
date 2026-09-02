"""
db/database.py

Fournit l'engine et la session SQLAlchemy à partir de DATABASE_URL.

- En Docker Compose (dev ou VM) : DATABASE_URL pointe vers PostgreSQL,
  construite depuis les variables .env (POSTGRES_USER/PASSWORD/DB/HOST/PORT).
- En tests locaux sans Docker : DATABASE_URL peut pointer vers un fichier
  SQLite (ex: "sqlite:///./test.db"), le code applicatif ne change pas.
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from models import Base


def _default_postgres_url() -> str:
    user = os.getenv("POSTGRES_USER", "exeiguard")
    password = os.getenv("POSTGRES_PASSWORD", "exeiguard_paie")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB", "exeiguard_poc")
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db}"


DATABASE_URL = os.getenv("DATABASE_URL", _default_postgres_url())

engine = create_engine(DATABASE_URL, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


def get_session() -> Session:
    return SessionLocal()


def init_db() -> None:
    """Créé les tables si elles n'existent pas encore (utile en dev/tests ;
    en PoC/prod réel, préférer `alembic upgrade head`)."""
    Base.metadata.create_all(bind=engine)
