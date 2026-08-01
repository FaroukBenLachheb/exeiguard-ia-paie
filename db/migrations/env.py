"""
db/migrations/env.py

Point d'entrée Alembic. Lit DATABASE_URL depuis l'environnement (cohérent
avec database.py) plutôt que de dupliquer la config dans alembic.ini.
"""

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Permet d'importer db/models.py quel que soit le dossier d'exécution
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _default_postgres_url() -> str:
    user = os.getenv("POSTGRES_USER", "exeiguard")
    password = os.getenv("POSTGRES_PASSWORD", "changeme_local")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB", "exeiguard_poc")
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db}"


def get_url() -> str:
    return os.getenv("DATABASE_URL", _default_postgres_url())


def run_migrations_offline() -> None:
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()
    connectable = engine_from_config(
        configuration, prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
