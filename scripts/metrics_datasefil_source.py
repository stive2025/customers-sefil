"""
Métrica de solo lectura: cuántos clientes tienen su información
(teléfonos, direcciones, correos y relaciones) creada total o
parcialmente desde la fuente DATA SEFIL.

Un cliente cuenta como:
  - "100% DATA SEFIL": todos sus registros de contacto/relación
    fueron creados por DATA SEFIL.
  - "Parcial": tiene al menos un registro de DATA SEFIL y al menos
    uno de otra fuente (Collecta, Leads, manual, etc).
  - "Sin DATA SEFIL": no tiene ningún registro creado por DATA SEFIL.

No modifica datos. Uso:
    python scripts/metrics_datasefil_source.py
"""
from sqlalchemy import text

from app.core.database import SessionLocal

DATASEFIL_MATCH = "UPPER(REPLACE(source, '_', ' ')) = 'DATA SEFIL'"

QUERY = f"""
WITH contactos AS (
    SELECT customer_id, created_source AS source FROM collection_phones
    UNION ALL
    SELECT customer_id, created_source AS source FROM collection_addresses
    UNION ALL
    SELECT customer_id, created_source AS source FROM collection_emails
    UNION ALL
    SELECT customer_id, source AS source FROM customer_relationships
),
agg AS (
    SELECT
        customer_id,
        COUNT(*) AS total_registros,
        COUNT(*) FILTER (WHERE {DATASEFIL_MATCH}) AS registros_datasefil
    FROM contactos
    WHERE source IS NOT NULL
    GROUP BY customer_id
)
SELECT
    (SELECT COUNT(*) FROM customers) AS total_clientes,
    COUNT(*) AS clientes_con_algun_registro,
    COUNT(*) FILTER (WHERE registros_datasefil = total_registros) AS clientes_100pct_datasefil,
    COUNT(*) FILTER (WHERE registros_datasefil > 0 AND registros_datasefil < total_registros) AS clientes_parcial_datasefil,
    COUNT(*) FILTER (WHERE registros_datasefil = 0) AS clientes_sin_datasefil
FROM agg;
"""

QUERY_POR_TIPO = f"""
SELECT 'phones' AS tipo,
       COUNT(*) FILTER (WHERE {DATASEFIL_MATCH.replace('source', 'created_source')}) AS registros_datasefil,
       COUNT(*) AS total_registros
FROM collection_phones
UNION ALL
SELECT 'addresses',
       COUNT(*) FILTER (WHERE {DATASEFIL_MATCH.replace('source', 'created_source')}),
       COUNT(*)
FROM collection_addresses
UNION ALL
SELECT 'emails',
       COUNT(*) FILTER (WHERE {DATASEFIL_MATCH.replace('source', 'created_source')}),
       COUNT(*)
FROM collection_emails
UNION ALL
SELECT 'relationships',
       COUNT(*) FILTER (WHERE {DATASEFIL_MATCH}),
       COUNT(*)
FROM customer_relationships;
"""


def main():
    db = SessionLocal()
    try:
        row = db.execute(text(QUERY)).mappings().first()
        print("=== Clientes por cobertura de fuente DATA SEFIL ===")
        print(f"Total clientes en el sistema:            {row['total_clientes']}")
        print(f"Clientes con algún dato de contacto:     {row['clientes_con_algun_registro']}")
        print(f"  - 100% DATA SEFIL:                     {row['clientes_100pct_datasefil']}")
        print(f"  - Parcial (mezcla de fuentes):          {row['clientes_parcial_datasefil']}")
        print(f"  - Sin ningún dato de DATA SEFIL:        {row['clientes_sin_datasefil']}")

        print("\n=== Desglose por tipo de registro ===")
        for r in db.execute(text(QUERY_POR_TIPO)).mappings():
            pct = (r["registros_datasefil"] / r["total_registros"] * 100) if r["total_registros"] else 0
            print(f"  {r['tipo']:<15} {r['registros_datasefil']:>6} / {r['total_registros']:<6} ({pct:.1f}% DATA SEFIL)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
