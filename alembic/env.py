from logging.config import fileConfig

from alembic import context
from sqlmodel import SQLModel

from database import engine
import models  # noqa: F401  (needed so Alembic can see our tables)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata

# Tables created by extensions (not by us). Alembic must never touch them.
EXCLUDED_TABLES = {"spatial_ref_sys"}


def include_object(object, name, type_, reflected, compare_to):
    if type_ == "table" and name in EXCLUDED_TABLES:
        return False
    if type_ == "index" and name and name.startswith("ix_perf_"):
        return False
    return True


def run_migrations_offline():
    context.configure(
        url=engine.url.render_as_string(hide_password=False),
        target_metadata=target_metadata,
        include_object=include_object,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()