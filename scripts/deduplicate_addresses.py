"""
Deja direcciones únicas por cliente en collection_addresses.

Criterio de duplicado (mismo cliente y misma clave normalizada):
    (address_line, city)  -> sin tildes, mayúsculas, espacios colapsados.
Es la misma clave que usa bulk_upsert._merge_addresses, pero normalizada
(así "Av. Amazonas  N24" y "AV. AMAZONAS N24" cuentan como la misma).

Qué registro se conserva en cada grupo de duplicados:
    1. activo sobre inactivo (deleted_at / is_active)
    2. el que tiene coordenadas (latitude/longitude)
    3. el más antiguo (menor id)

Antes de borrar, el registro conservado hereda de los duplicados los
campos que tenga vacíos (province, canton, parish, neighborhood,
address_type, latitude, longitude) y se suman count_effective /
count_not_effective, para no perder información.

Uso:
    python scripts/deduplicate_addresses.py --dry-run   # solo reporta
    python scripts/deduplicate_addresses.py             # aplica el cambio
"""
import argparse
import re
import unicodedata
from collections import defaultdict

from sqlalchemy import text

from app.core.database import SessionLocal

FILL_FIELDS = ("province", "canton", "parish", "neighborhood", "address_type", "latitude", "longitude")
SUM_FIELDS = ("count_effective", "count_not_effective")
DELETE_BATCH = 1000
SAMPLE_SIZE = 10


def normalize(value: str | None) -> str:
    if not value:
        return ""
    stripped = "".join(c for c in unicodedata.normalize("NFD", value) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", stripped).strip().upper()


def keeper_rank(row) -> tuple:
    is_active = bool(row["is_active"]) and row["deleted_at"] is None
    has_coords = row["latitude"] is not None and row["longitude"] is not None
    return (0 if is_active else 1, 0 if has_coords else 1, row["id"])


def main():
    parser = argparse.ArgumentParser(description="Elimina direcciones duplicadas por cliente.")
    parser.add_argument("--dry-run", action="store_true", help="Modo seguro: solo reporta, no modifica datos.")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        print(f"Iniciando deduplicación de direcciones (Dry-run: {args.dry_run})...")

        rows = db.execute(text("""
            SELECT id, customer_id, address_line, city, province, canton, parish, neighborhood,
                   address_type, latitude, longitude, count_effective, count_not_effective,
                   is_active, deleted_at
            FROM collection_addresses
            ORDER BY customer_id, id
        """)).mappings().all()

        groups: dict[tuple, list] = defaultdict(list)
        for row in rows:
            groups[(row["customer_id"], normalize(row["address_line"]), normalize(row["city"]))].append(row)

        duplicate_groups = {k: v for k, v in groups.items() if len(v) > 1}
        ids_to_delete: list[int] = []
        updates: list[dict] = []

        for group in duplicate_groups.values():
            ordered = sorted(group, key=keeper_rank)
            keeper, dupes = ordered[0], ordered[1:]

            changes = {}
            for field in FILL_FIELDS:
                if keeper[field] is None:
                    donor = next((d[field] for d in dupes if d[field] is not None), None)
                    if donor is not None:
                        changes[field] = donor
            for field in SUM_FIELDS:
                values = [r[field] for r in group if r[field] is not None]
                if len(values) > 1:
                    changes[field] = sum(values)
            if changes:
                updates.append({"id": keeper["id"], **changes})
            ids_to_delete.extend(d["id"] for d in dupes)

        customers_affected = len({k[0] for k in duplicate_groups})
        print(f"Total direcciones: {len(rows)}")
        print(f"Grupos duplicados: {len(duplicate_groups)} en {customers_affected} clientes")
        print(f"Direcciones a eliminar: {len(ids_to_delete)} (quedarían {len(rows) - len(ids_to_delete)})")
        print(f"Direcciones conservadas que heredan datos de duplicados: {len(updates)}")

        if args.dry_run:
            print(f"\n[DRY-RUN] Ejemplos (hasta {SAMPLE_SIZE} grupos):")
            for (customer_id, addr, city), group in list(duplicate_groups.items())[:SAMPLE_SIZE]:
                print(f"  cliente {customer_id}: '{addr}' / '{city}' -> ids {[r['id'] for r in group]}")
            print("\n[DRY-RUN] No se modificó ningún dato.")
            return

        for change in updates:
            row_id = change.pop("id")
            assignments = ", ".join(f"{field} = :{field}" for field in change)
            db.execute(text(f"UPDATE collection_addresses SET {assignments} WHERE id = :id"), {**change, "id": row_id})

        deleted = 0
        for i in range(0, len(ids_to_delete), DELETE_BATCH):
            batch = ids_to_delete[i:i + DELETE_BATCH]
            deleted += db.execute(
                text("DELETE FROM collection_addresses WHERE id = ANY(:ids)"), {"ids": batch}
            ).rowcount

        db.commit()
        print(f"\nÉxito: {deleted} direcciones duplicadas eliminadas, {len(updates)} conservadas actualizadas.")

    except Exception as e:
        print(f"Ocurrió un error: {e}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    main()
