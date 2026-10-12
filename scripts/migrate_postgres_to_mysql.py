"""
Migra TODA la base PostgreSQL (esquema + datos) a una base MySQL/MariaDB remota.

El esquema se lee por reflexión directamente de PostgreSQL (no de los modelos),
así que se copian todas las tablas existentes, incluida alembic_version.

Qué hace:
    1. Refleja tablas, columnas, PK, FK, índices y constraints únicos de Postgres.
    2. Traduce tipos a MySQL:
         JSONB/JSON/ARRAY -> JSON          TIMESTAMP(tz) -> DATETIME(6) en UTC
         UUID -> CHAR(36)                  TEXT -> LONGTEXT
         NUMERIC sin precisión -> DECIMAL(38,10)   BYTEA -> LONGBLOB
       y los server_default (now() -> CURRENT_TIMESTAMP(6), true/false -> 1/0,
       'x'::character varying -> 'x'; nextval() se reemplaza por AUTO_INCREMENT).
    3. Crea las tablas en MySQL (InnoDB, utf8mb4).
    4. Copia los datos por lotes respetando el orden de dependencias de FK,
       con FOREIGN_KEY_CHECKS=0 durante la carga, haciendo commit por lote.
    5. Verifica que el número de filas de cada tabla coincida en origen y destino.

No se migran vistas, funciones, triggers ni índices por expresión de Postgres.

Requiere el driver de Postgres, que ya no está en requirements.txt:
    pip install psycopg2-binary

Configuración (variables de entorno o archivo .env en la raíz del proyecto):
    POSTGRES_URL     origen Postgres (por defecto localhost:5432/centralizacion_db)
    MYSQL_HOST       servidor MySQL destino
    MYSQL_PORT       puerto (por defecto 3306)
    MYSQL_DATABASE   nombre de la base destino
    MYSQL_USER       usuario
    MYSQL_PASSWORD   contraseña (si falta, se pide por consola)

Uso:
    python scripts/migrate_postgres_to_mysql.py --dry-run          # muestra DDL y conteos, no toca MySQL
    python scripts/migrate_postgres_to_mysql.py                    # migra (falla si ya existen tablas)
    python scripts/migrate_postgres_to_mysql.py --drop-existing    # borra y recrea las tablas destino
    python scripts/migrate_postgres_to_mysql.py --tables customers collection_phones
"""
import argparse
import getpass
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKeyConstraint,
    Index,
    Integer,
    Interval,
    LargeBinary,
    MetaData,
    Numeric,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Table,
    Text,
    Time,
    UniqueConstraint,
    Uuid,
    create_engine,
    func,
    insert,
    inspect,
    select,
    text,
)
from sqlalchemy.dialects import mysql, postgresql
from sqlalchemy.engine import URL
from sqlalchemy.schema import CreateIndex, CreateTable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PG_URL = "postgresql+psycopg2://postgres:S3F1L_Dev@localhost:5432/centralizacion_db"

MYSQL_IDENTIFIER_MAX = 64
MAX_INDEX_CHARS = 768          # 768 * 4 bytes (utf8mb4) = 3072 bytes, límite de InnoDB
TEXT_INDEX_PREFIX = 255


# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

def load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(PROJECT_ROOT / ".env")


def build_mysql_url() -> URL:
    missing = [k for k in ("MYSQL_HOST", "MYSQL_DATABASE", "MYSQL_USER") if not os.getenv(k)]
    if missing:
        sys.exit(f"Faltan variables de entorno para MySQL: {', '.join(missing)}")
    password = os.getenv("MYSQL_PASSWORD") or getpass.getpass("Contraseña MySQL: ")
    # URL.create escapa caracteres especiales de la contraseña (@, %, etc.)
    return URL.create(
        "mysql+pymysql",
        username=os.environ["MYSQL_USER"],
        password=password,
        host=os.environ["MYSQL_HOST"],
        port=int(os.getenv("MYSQL_PORT", "3306")),
        database=os.environ["MYSQL_DATABASE"],
        query={"charset": "utf8mb4"},
    )


# ---------------------------------------------------------------------------
# Conversión de tipos y valores
# ---------------------------------------------------------------------------

def _to_utc_naive(value):
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _interval_to_str(value):
    if isinstance(value, timedelta):
        total = int(value.total_seconds())
        sign = "-" if total < 0 else ""
        h, rem = divmod(abs(total), 3600)
        m, s = divmod(rem, 60)
        return f"{sign}{h:02d}:{m:02d}:{s:02d}"
    return str(value)


def _uuid_to_str(value):
    return str(value) if isinstance(value, uuid.UUID) else value


def _jsonable(value):
    # ARRAY y valores raros se guardan como JSON; json.dumps(default=str) cubre fechas/Decimal.
    return json.loads(json.dumps(value, default=str))


def _to_str(value):
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str, ensure_ascii=False)
    return str(value)


def convert_type(col_type):
    """Devuelve (tipo_mysql, conversor_de_valor | None)."""
    t = col_type
    if isinstance(t, (postgresql.JSONB, postgresql.JSON)) or t.__class__.__name__ == "JSON":
        return mysql.JSON(none_as_null=True), None
    if isinstance(t, postgresql.ARRAY):
        return mysql.JSON(none_as_null=True), _jsonable
    if isinstance(t, (postgresql.UUID, Uuid)):
        return CHAR(36), _uuid_to_str
    if isinstance(t, (postgresql.INET, postgresql.CIDR, postgresql.MACADDR)):
        return String(64), _to_str
    if isinstance(t, (postgresql.INTERVAL, Interval)):
        return String(64), _interval_to_str
    if isinstance(t, postgresql.MONEY):
        return Numeric(19, 4), None
    if isinstance(t, (postgresql.BYTEA, LargeBinary)):
        return mysql.LONGBLOB(), None
    if isinstance(t, DateTime):
        return mysql.DATETIME(fsp=6), _to_utc_naive
    if isinstance(t, Time):
        return mysql.TIME(fsp=6), lambda v: v.replace(tzinfo=None)
    if isinstance(t, Date):
        return Date(), None
    if isinstance(t, Boolean):
        return Boolean(create_constraint=False), None
    if isinstance(t, Enum):
        return mysql.ENUM(*t.enums), None
    if isinstance(t, Float) or isinstance(t, postgresql.DOUBLE_PRECISION):
        return mysql.DOUBLE(), None
    if isinstance(t, Numeric):
        if t.precision is None:
            return mysql.DECIMAL(38, 10), None
        return mysql.DECIMAL(min(t.precision, 65), min(t.scale or 0, 30)), None
    if isinstance(t, BigInteger):
        return BigInteger(), None
    if isinstance(t, SmallInteger):
        return SmallInteger(), None
    if isinstance(t, Integer):
        return Integer(), None
    if isinstance(t, Text) or (isinstance(t, String) and t.length is None):
        return mysql.LONGTEXT(), None
    if isinstance(t, String):
        if t.length > 16383:  # máximo VARCHAR en utf8mb4
            return mysql.LONGTEXT(), None
        return (CHAR(t.length) if isinstance(t, CHAR) else String(t.length)), None
    print(f"   ! Tipo no reconocido {t!r}: se migra como LONGTEXT")
    return mysql.LONGTEXT(), _to_str


def is_text_like(mysql_type) -> bool:
    return isinstance(mysql_type, (mysql.LONGTEXT, mysql.JSON, mysql.LONGBLOB))


_CAST_RE = re.compile(r"::[\w\s\"]+(\[\])?")


def convert_server_default(column, mysql_type):
    """Traduce el server_default de Postgres a MySQL, o None si no aplica."""
    if column.server_default is None:
        return None
    raw = str(getattr(column.server_default, "arg", column.server_default))
    if "nextval(" in raw:
        return None
    if is_text_like(mysql_type):
        return None  # MySQL < 8.0.13 no admite DEFAULT en TEXT/JSON/BLOB
    value = _CAST_RE.sub("", raw).strip()
    while value.startswith("(") and value.endswith(")"):
        value = value[1:-1].strip()
    lowered = value.lower()

    if lowered in ("now()", "current_timestamp", "localtimestamp", "transaction_timestamp()",
                   "statement_timestamp()", "clock_timestamp()"):
        if isinstance(mysql_type, mysql.DATETIME):
            return text("CURRENT_TIMESTAMP(6)")
        return None
    if lowered == "current_date":
        return None  # DEFAULT CURRENT_DATE no es portable entre versiones de MySQL
    if lowered in ("true", "false"):
        return text("1" if lowered == "true" else "0")
    if re.fullmatch(r"-?\d+(\.\d+)?", value):
        return text(value)
    if re.fullmatch(r"'(?:[^']|'')*'", value):
        return text(value)
    print(f"   ! Default no traducible en {column.table.name}.{column.name}: {raw!r} (se omite)")
    return None


# ---------------------------------------------------------------------------
# Construcción del esquema destino
# ---------------------------------------------------------------------------

def mysql_name(name: str) -> str:
    return name if len(name) <= MYSQL_IDENTIFIER_MAX else name[:MYSQL_IDENTIFIER_MAX]


def is_autoincrement(src_col) -> bool:
    if not src_col.primary_key or not isinstance(src_col.type, Integer):
        return False
    default = str(getattr(src_col.server_default, "arg", "") or "")
    return "nextval(" in default or src_col.identity is not None or src_col.autoincrement is True


def build_target_table(src_table: Table, dst_meta: MetaData, collation: str, included: set):
    converters = {}
    columns = []
    pk_cols = [c.name for c in src_table.primary_key.columns]
    single_int_pk = len(pk_cols) == 1

    for src_col in src_table.columns:
        dst_type, conv = convert_type(src_col.type)
        if conv:
            converters[src_col.name] = conv
        autoinc = single_int_pk and is_autoincrement(src_col)
        columns.append(Column(
            src_col.name,
            dst_type,
            nullable=src_col.nullable,
            autoincrement=autoinc,
            server_default=None if autoinc else convert_server_default(src_col, dst_type),
            comment=src_col.comment,
        ))

    dst_table = Table(
        src_table.name, dst_meta, *columns,
        comment=src_table.comment,
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate=collation,
    )
    if pk_cols:
        dst_table.append_constraint(PrimaryKeyConstraint(*pk_cols))

    for fk in src_table.foreign_key_constraints:
        ref_table = fk.referred_table.name
        if ref_table not in included:
            print(f"   ! FK {fk.name} omitida: la tabla {ref_table} no se migra")
            continue
        dst_table.append_constraint(ForeignKeyConstraint(
            [c.name for c in fk.columns],
            [f"{ref_table}.{e.column.name}" for e in fk.elements],
            name=mysql_name(fk.name) if fk.name else None,
            ondelete=fk.ondelete,
            onupdate=fk.onupdate,
        ))

    def prefix_lengths(col_names):
        lengths = {}
        for name in col_names:
            col_type = dst_table.c[name].type
            if is_text_like(col_type):
                lengths[name] = TEXT_INDEX_PREFIX
            elif isinstance(col_type, String) and col_type.length and col_type.length > MAX_INDEX_CHARS:
                lengths[name] = MAX_INDEX_CHARS
        return lengths

    for uq in (c for c in src_table.constraints if isinstance(c, UniqueConstraint)):
        names = [c.name for c in uq.columns]
        lengths = prefix_lengths(names)
        if lengths:
            print(f"   ! UNIQUE {uq.name} usa prefijo en {lengths}: la unicidad será por prefijo")
        Index(mysql_name(uq.name or f"uq_{src_table.name}_{'_'.join(names)}"),
              *[dst_table.c[n] for n in names], unique=True,
              **({"mysql_length": lengths} if lengths else {}))

    for idx in src_table.indexes:
        if any(not isinstance(e, Column) for e in idx.expressions):
            print(f"   ! Índice por expresión {idx.name} omitido")
            continue
        if idx.dialect_options["postgresql"].get("where") is not None:
            print(f"   ! Índice parcial {idx.name} se crea sin la condición WHERE")
        names = [c.name for c in idx.columns]
        lengths = prefix_lengths(names)
        Index(mysql_name(idx.name), *[dst_table.c[n] for n in names], unique=idx.unique,
              **({"mysql_length": lengths} if lengths else {}))

    return dst_table, converters


# ---------------------------------------------------------------------------
# Copia de datos
# ---------------------------------------------------------------------------

def count_rows(conn, table) -> int:
    return conn.execute(select(func.count()).select_from(table)).scalar_one()


def copy_table(src_engine, dst_engine, src_table, dst_table, converters, batch_size) -> int:
    order_by = list(src_table.primary_key.columns) or list(src_table.columns)[:1]
    col_names = [c.name for c in src_table.columns]
    conv_list = [(i, converters[n]) for i, n in enumerate(col_names) if n in converters]
    stmt = insert(dst_table)
    copied = 0
    started = time.monotonic()

    with src_engine.connect() as sconn, dst_engine.connect() as dconn:
        dconn.exec_driver_sql("SET FOREIGN_KEY_CHECKS=0")
        result = sconn.execution_options(stream_results=True, yield_per=batch_size).execute(
            select(src_table).order_by(*order_by)
        )
        for partition in result.partitions():
            rows = []
            for row in partition:
                values = list(row)
                for i, conv in conv_list:
                    if values[i] is not None:
                        values[i] = conv(values[i])
                rows.append(dict(zip(col_names, values)))
            dconn.execute(stmt, rows)
            dconn.commit()
            copied += len(rows)
            elapsed = time.monotonic() - started
            print(f"\r   {copied:>10,} filas  ({copied / max(elapsed, 0.001):,.0f} filas/s)", end="", flush=True)
        dconn.exec_driver_sql("SET FOREIGN_KEY_CHECKS=1")
    print()
    return copied


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Migra la base PostgreSQL completa a MySQL.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Solo muestra el DDL MySQL y los conteos de origen; no se conecta a MySQL.")
    parser.add_argument("--drop-existing", action="store_true",
                        help="Elimina en MySQL las tablas a migrar antes de crearlas.")
    parser.add_argument("--tables", nargs="+", help="Migrar solo estas tablas (por defecto, todas).")
    parser.add_argument("--batch-size", type=int, default=2000, help="Filas por lote (default 2000).")
    parser.add_argument("--schema", default="public", help="Esquema Postgres de origen (default public).")
    parser.add_argument("--collation", default="utf8mb4_bin",
                        help="Collation MySQL (default utf8mb4_bin: comparación exacta como Postgres; "
                             "use utf8mb4_unicode_ci para comparaciones sin mayúsculas/tildes).")
    args = parser.parse_args()

    load_env()
    pg_url = os.getenv("POSTGRES_URL", DEFAULT_PG_URL)
    src_engine = create_engine(pg_url)

    print(f"Origen  : {src_engine.url.render_as_string(hide_password=True)}")
    src_meta = MetaData(schema=None)
    src_meta.reflect(bind=src_engine, schema=args.schema, views=False)
    src_tables = {t.name: t for t in src_meta.sorted_tables}

    if args.tables:
        unknown = set(args.tables) - set(src_tables)
        if unknown:
            sys.exit(f"Tablas inexistentes en origen: {', '.join(sorted(unknown))}")
        src_tables = {n: t for n, t in src_tables.items() if n in args.tables}
    included = set(src_tables)
    print(f"Tablas  : {len(src_tables)} -> {', '.join(src_tables)}\n")

    dst_meta = MetaData()
    plan = []
    for name, src_table in src_tables.items():
        print(f"- Esquema {name}")
        dst_table, converters = build_target_table(src_table, dst_meta, args.collation, included)
        plan.append((src_table, dst_table, converters))

    source_counts = {}
    with src_engine.connect() as sconn:
        for src_table, _, _ in plan:
            source_counts[src_table.name] = count_rows(sconn, src_table)

    if args.dry_run:
        dialect = mysql.dialect()
        for src_table, dst_table, _ in plan:
            print(f"\n-- {dst_table.name}: {source_counts[src_table.name]:,} filas")
            print(str(CreateTable(dst_table).compile(dialect=dialect)).strip() + ";")
            for idx in dst_table.indexes:
                print(str(CreateIndex(idx).compile(dialect=dialect)).strip() + ";")
        print("\nDry-run: no se modificó MySQL.")
        return

    dst_engine = create_engine(build_mysql_url(), pool_pre_ping=True, pool_recycle=280)
    print(f"Destino : {dst_engine.url.render_as_string(hide_password=True)}")
    with dst_engine.connect() as dconn:
        version = dconn.exec_driver_sql("SELECT VERSION()").scalar()
        print(f"Servidor: MySQL {version}\n")
        existing = set(inspect(dconn).get_table_names()) & included

    if existing and not args.drop_existing:
        sys.exit(f"Ya existen en MySQL: {', '.join(sorted(existing))}. "
                 "Use --drop-existing para reemplazarlas.")

    with dst_engine.begin() as dconn:
        dconn.exec_driver_sql("SET FOREIGN_KEY_CHECKS=0")
        if existing:
            print(f"Eliminando tablas existentes: {', '.join(sorted(existing))}")
            for _, dst_table, _ in reversed(plan):
                if dst_table.name in existing:
                    dconn.exec_driver_sql(f"DROP TABLE IF EXISTS `{dst_table.name}`")
        dst_meta.create_all(dconn)
        dconn.exec_driver_sql("SET FOREIGN_KEY_CHECKS=1")
    print("Tablas creadas en MySQL.\n")

    for src_table, dst_table, converters in plan:
        print(f"- Copiando {src_table.name} ({source_counts[src_table.name]:,} filas)")
        copy_table(src_engine, dst_engine, src_table, dst_table, converters, args.batch_size)

    print("\nVerificación de conteos:")
    mismatches = 0
    with dst_engine.connect() as dconn:
        for src_table, dst_table, _ in plan:
            src_n = source_counts[src_table.name]
            dst_n = count_rows(dconn, dst_table)
            status = "OK" if src_n == dst_n else "DIFERENTE"
            mismatches += src_n != dst_n
            print(f"  {src_table.name:<35} postgres={src_n:>10,}  mysql={dst_n:>10,}  {status}")

    if mismatches:
        sys.exit(f"\n{mismatches} tabla(s) con conteos diferentes.")
    print("\nMigración completada sin diferencias.")


if __name__ == "__main__":
    main()
