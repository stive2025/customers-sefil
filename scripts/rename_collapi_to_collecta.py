"""
Backfill: renombra la fuente "collapi" a "Collecta" en los registros
YA EXISTENTES en base de datos.

"Collapi" es el subdominio real de la API de Collecta
(https://collapi.sefil.com.ec/...) — nunca fue una fuente separada.
Desde que se agregó la normalización en los schemas de sync
(app/schemas/sync.py, app/api/routers/sync.py) las nuevas
sincronizaciones ya no guardan "collapi" crudo, pero pudieron quedar
registros históricos con ese valor (incluyendo los que el script viejo
`fix_collapi_and_addresses.py` no corrigió: ese script comparaba
`hasattr(model, 'created_source')`, lo cual excluye por error a
CustomerRelationship, que usa la columna `source`).

Tablas/columnas afectadas:
  - collection_phones.created_source
  - collection_addresses.created_source
  - collection_emails.created_source
  - customer_relationships.source

El match es insensible a mayúsculas/minúsculas (cubre "collapi",
"Collapi", "COLLAPI").

Uso:
    python scripts/rename_collapi_to_collecta.py --dry-run   # solo cuenta
    python scripts/rename_collapi_to_collecta.py             # aplica el cambio
"""
import argparse

from sqlalchemy import text

from app.core.database import SessionLocal

NEW_SOURCE = "Collecta"
MATCH = "UPPER({col}) = 'COLLAPI'"

TARGETS = [
    ("collection_phones", "created_source"),
    ("collection_addresses", "created_source"),
    ("collection_emails", "created_source"),
    ("customer_relationships", "source"),
]


def main():
    parser = argparse.ArgumentParser(description="Renombra la fuente collapi a Collecta en los registros existentes.")
    parser.add_argument("--dry-run", action="store_true", help="Modo seguro: solo cuenta cuántos registros se actualizarían.")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        print(f"Iniciando renombrado collapi -> {NEW_SOURCE} (Dry-run: {args.dry_run})...")
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
