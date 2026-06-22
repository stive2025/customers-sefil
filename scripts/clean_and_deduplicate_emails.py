import argparse
from sqlalchemy import text
from app.core.database import SessionLocal

def main():
    parser = argparse.ArgumentParser(description="Limpia correos basura y elimina duplicados por cliente.")
    parser.add_argument("--dry-run", action="store_true", help="Modo seguro: simula pero no ejecuta los DELETE.")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        print(f"Iniciando limpieza de correos (Dry-run: {args.dry_run})...")

        if args.dry_run:
            # Contar basura
            res_junk = db.execute(text(
                "SELECT COUNT(*) FROM collection_emails WHERE email_address ILIKE 'vacunacion%' OR email_address ILIKE 'soporte.covid%'"
            )).scalar()
            print(f"[DRY-RUN] Se detectarón {res_junk} correos basura ('vacunacion' o 'soporte.covid').")

            # Contar duplicados exactos usando subquery
            res_dup = db.execute(text("""
                SELECT COUNT(*) FROM collection_emails e1
                INNER JOIN collection_emails e2 
                ON e1.customer_id = e2.customer_id 
                AND e1.email_address = e2.email_address
                WHERE e1.id > e2.id
            """)).scalar()
            print(f"[DRY-RUN] Se detectarón {res_dup} correos duplicados exactos (mismo customer_id y email_address).")

        else:
            # 1. Eliminar basura
            res_junk = db.execute(text(
                "DELETE FROM collection_emails WHERE email_address ILIKE 'vacunacion%' OR email_address ILIKE 'soporte.covid%'"
            ))
            print(f"Borrados {res_junk.rowcount} correos basura.")

            # 2. Eliminar duplicados usando SQL nativo (Postgres sintaxis equivalente al INNER JOIN de MySQL)
            res_dup = db.execute(text("""
                DELETE FROM collection_emails a
                USING collection_emails b
                WHERE a.id > b.id
                AND a.customer_id = b.customer_id
                AND a.email_address = b.email_address
            """))
            print(f"Borrados {res_dup.rowcount} correos duplicados exactos.")
            
            db.commit()
            print("Limpieza completada y guardada en base de datos.")

    except Exception as e:
        print(f"Ocurrió un error: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    main()
