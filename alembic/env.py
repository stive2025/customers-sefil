"""
Configuración de Alembic para el entorno de migraciones.
Modificado para soportar autogenerate con todos los modelos del proyecto.
"""

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

# ---------------------------------------------------------------------------
# MODIFICACIÓN 1: Agregar la raíz del proyecto al PYTHONPATH
# Esto permite importar los módulos de 'app' sin instalar el paquete.
# ---------------------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

# ---------------------------------------------------------------------------
# MODIFICACIÓN 2: Importar todos los modelos para que Alembic los detecte.
# Es CRÍTICO importar app.models (el __init__.py centralizado) para que
# el metadata de Base registre todas las tablas.
# ---------------------------------------------------------------------------
from app.models import Base  # noqa: E402 — importa todos los modelos vía __init__.py
from app.core.database import DATABASE_URL  # noqa: E402

# ---------------------------------------------------------------------------
# Configuración estándar de Alembic
# ---------------------------------------------------------------------------
config = context.config

# Interpretar el archivo de configuración para el logging de Python
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ---------------------------------------------------------------------------
# MODIFICACIÓN 3: Asignar el metadata de Base a target_metadata.
# Esto es lo que habilita el --autogenerate.
# ---------------------------------------------------------------------------
target_metadata = Base.metadata

# ---------------------------------------------------------------------------
# MODIFICACIÓN 4: Sobrescribir la URL de la BD desde la variable de entorno.
# Evita hardcodear credenciales en alembic.ini.
# ---------------------------------------------------------------------------
config.set_main_option("sqlalchemy.url", DATABASE_URL)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,          # Detecta cambios de tipo de columna
        compare_server_default=True, # Detecta cambios en valores por defecto
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,           # Detecta cambios de tipo de columna
            compare_server_default=True,  # Detecta cambios en valores por defecto
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
