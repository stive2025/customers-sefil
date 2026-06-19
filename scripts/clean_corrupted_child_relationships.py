import argparse
from datetime import date
from sqlalchemy import select
from app.core.database import SessionLocal
from app.models.customer import Customer
from app.models.relationships import CustomerRelationship

def calculate_age_at_birth(parent_birth: date, child_birth: date) -> int | None:
    """
    Calcula la edad del padre en el momento exacto en que nació el hijo.
    Si el hijo nació antes que el padre, retornará un número negativo.
    """
    if not parent_birth or not child_birth:
        return None
    
    years = child_birth.year - parent_birth.year
    # Restar 1 si el mes/día de nacimiento del hijo es anterior al del padre en ese año
    if (child_birth.month, child_birth.day) < (parent_birth.month, parent_birth.day):
        years -= 1
        
    return years

def main():
    parser = argparse.ArgumentParser(description="Limpia relaciones de hijos corruptas (imposibles por fecha de nacimiento).")
    parser.add_argument("--dry-run", action="store_true", help="Modo seguro: solo imprime en consola, NO elimina.")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        # Buscar todas las relaciones de tipo HIJO o HIJA haciendo un JOIN con el padre/madre (Customer)
        query = select(CustomerRelationship, Customer).join(
            Customer, CustomerRelationship.customer_id == Customer.id
        ).where(
            CustomerRelationship.relationship_type.in_(["HIJO", "HIJA"])
        )

        corrupt_count = 0
        total_checked = 0

        print(f"Iniciando evaluación de relaciones (Dry-run: {args.dry_run})...")

        # Usar yield_per(500) para traer lotes de 500 registros y evitar OutOfMemory (RAM)
        for rel, parent in db.execute(query).yield_per(500):
            total_checked += 1
            
            parent_birth = parent.birth_date
            child_birth = rel.related_birth_date

            # Si alguno no tiene fecha de nacimiento, lo ignoramos
            if not parent_birth or not child_birth:
                continue

            age_at_birth = calculate_age_at_birth(parent_birth, child_birth)
            
            # Si es matemáticamente imposible (nació antes, o a una edad menor a 13)
            if age_at_birth is not None and age_at_birth < 13:
                corrupt_count += 1
                if args.dry_run:
                    print(f"[DRY-RUN] CORRUPCIÓN DETECTADA (ID Relación: {rel.id}):")
                    print(f"  Padre/Madre: {parent.first_name} {parent.last_name} (Nace: {parent_birth})")
                    print(f"  Hijo/Hija: {rel.related_name} (Nace: {child_birth})")
                    print(f"  Edad del progenitor al nacer el hijo: {age_at_birth} años\n")
                else:
                    print(f"Eliminando relación ID {rel.id} (Edad progenitor: {age_at_birth})...")
                    db.delete(rel)
        
        if not args.dry_run:
            db.commit()
            print(f"Limpieza completada. Se eliminaron definitivamente {corrupt_count} relaciones corruptas.")
        else:
            print(f"Dry-run completado. Se habrían eliminado {corrupt_count} relaciones corruptas.")
        
        print(f"Total de relaciones evaluadas: {total_checked}")

    except Exception as e:
        print(f"Ocurrió un error: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    main()
