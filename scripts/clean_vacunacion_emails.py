import argparse
from sqlalchemy import select, delete
from app.core.database import SessionLocal
from app.models.collections import CollectionEmail

def main():
    parser = argparse.ArgumentParser(description="Limpia correos que empiezan con 'vacunacion'.")
    parser.add_argument("--dry-run", action="store_true", help="Modo seguro: solo imprime en consola, NO elimina.")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        # Buscar correos que empiezan con "vacunacion" (case-insensitive)
        query = select(CollectionEmail).where(
            CollectionEmail.email_address.ilike("vacunacion%")
        )
        
        emails_to_delete = db.execute(query).scalars().all()
        count = len(emails_to_delete)
        
        if args.dry_run:
            print(f"[DRY-RUN] Se encontrarón {count} correos basura que empiezan con 'vacunacion':")
            for e in emails_to_delete:
                print(f" - {e.email_address} (ID: {e.id}, Creado por: {e.created_source})")
        else:
            if count > 0:
                # Eliminación masiva eficiente
                stmt = delete(CollectionEmail).where(CollectionEmail.email_address.ilike("vacunacion%"))
                db.execute(stmt)
                db.commit()
                print(f"Limpieza completada. Se eliminaron definitivamente {count} correos basura de vacunación.")
            else:
                print("No se encontraron correos para limpiar.")
    except Exception as e:
        print(f"Ocurrió un error: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    main()
