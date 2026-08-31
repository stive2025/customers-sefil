"""
Backfill: renombra la fuente "DATA SEFIL" a "Diverservice" en los
registros YA EXISTENTES en base de datos.

No toca el código (el ETL de app/services/etl_datasefil.py sigue
guardando "DATA SEFIL" en las próximas sincronizaciones — este script
es solo una corrección histórica de los datos ya cargados).

Tablas/columnas afectadas:
  - collection_phones.created_source
  - collection_addresses.created_source
  - collection_emails.created_source
  - customer_relationships.source

El match es insensible a mayúsculas/minúsculas y a "_" vs " "
(cubre variantes como "DATA_SEFIL", "Datasefil", "DATASEFIL").

Uso:
    python scripts/rename_datasefil_to_diverservice.py --dry-run   # solo cuenta
    python scripts/rename_datasefil_to_diverservice.py             # aplica el cambio
"""
import argparse

from sqlalchemy import text

from app.core.database import SessionLocal

NEW_SOURCE = "Diverservice"
MATCH = "UPPER(REPLACE({col}, '_', ' ')) = 'DATA SEFIL'"

TARGETS = [
    ("collection_phones", "created_source"),
    ("collection_addresses", "created_source"),
    ("collection_emails", "created_source"),
    ("customer_relationships", "source"),
]


def main():
    parser = argparse.ArgumentParser(description="Renombra la fuente DATA SEFIL a Diverservice en los registros existentes.")
    parser.add_argument("--dry-run", action="store_true", help="Modo seguro: solo cuenta cuántos registros se actualizarían.")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        print(f"Iniciando renombrado DATA SEFIL -> {NEW_SOURCE} (Dry-run: {args.dry_run})...")
        total = 0
        for table, col in TARGETS:
            where = MATCH.format(col=col)
            if args.dry_run:
                count = db.execute(text(f"SELECT COUNT(*) FROM {table} WHERE {where}")).scalar()
                print(f"[DRY-RUN] {table}.{col}: {count} registros se actualizarían.")
                total += count
            else:
                result = db.execute(text(
                    f"UPDATE {table} SET {col} = :new_source WHERE {where}"
                ), {"new_source": NEW_SOURCE})
                print(f"{table}.{col}: {result.rowcount} registros actualizados.")
                total += result.rowcount

        if args.dry_run:
            print(f"\n[DRY-RUN] Total: {total} registros se actualizarían a '{NEW_SOURCE}'.")
        else:
            db.commit()
            print(f"\nÉxito: {total} registros actualizados a '{NEW_SOURCE}'.")

    except Exception as e:
        db.rollback()
        print(f"Ocurrió un error: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
