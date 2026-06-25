import argparse
from sqlalchemy import text
from app.core.database import SessionLocal

def main():
    parser = argparse.ArgumentParser(description="Actualiza is_verified=True para los teléfonos existentes de Collecta o Manual.")
    parser.add_argument("--dry-run", action="store_true", help="Modo seguro: solo cuenta los registros a actualizar.")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        print(f"Iniciando actualización de teléfonos (Dry-run: {args.dry_run})...")

        if args.dry_run:
            # Contar teléfonos de Collecta o Manual que aún no están verificados
            res = db.execute(text(
                "SELECT COUNT(*) FROM collection_phones WHERE (created_source = 'Collecta' OR created_source = 'Manual' OR updated_source = 'Collecta') AND is_verified = false"
            )).scalar()
            print(f"[DRY-RUN] Se actualizarán {res} teléfonos a is_verified=True.")
        else:
            # Actualizar
            res = db.execute(text(
                "UPDATE collection_phones SET is_verified = true WHERE (created_source = 'Collecta' OR created_source = 'Manual' OR updated_source = 'Collecta') AND is_verified = false"
            ))
            print(f"Éxito: Se actualizaron {res.rowcount} teléfonos existentes.")
            db.commit()

    except Exception as e:
        print(f"Ocurrió un error: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    main()
