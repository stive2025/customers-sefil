import sys
from pathlib import Path

# Agregar la raíz del proyecto al sys.path para poder importar módulos de la app
sys.path.append(str(Path(__file__).resolve().parent.parent))

import unicodedata
from sqlalchemy import select
from app.core.database import SessionLocal
from app.models.collections import CollectionPhone
from app.services.data_cleaning import infer_phone_type

def normalize_type_string(val: str) -> str | None:
    if not val:
        return None
    # Eliminar tildes y caracteres diacríticos (ej: MÓVIL -> MOVIL)
    val = ''.join(c for c in unicodedata.normalize('NFD', val) if unicodedata.category(c) != 'Mn')
    val = val.upper().strip()
    
    if val in ("MOVIL", "MOBILE", "CELULAR", "CEL", "MOBI", "CELU"):
        return "MOVIL"
    if val in ("FIJO", "CONVENCIONAL", "CASA", "TRABAJO", "DOMICILIO", "WORK", "HOME", "CONV", "OFICINA"):
        return "FIJO"
    if "MOVIL" in val or "MOBILE" in val or "CEL" in val:
        return "MOVIL"
    if "FIJO" in val or "CONV" in val or "CASA" in val:
        return "FIJO"
    return None

def main():
    db = SessionLocal()
    try:
        # Seleccionar teléfonos que no sean "FIJO" o "MOVIL" exactos, o que sean NULL
        stmt = select(CollectionPhone).where(
            CollectionPhone.phone_type.notin_(["FIJO", "MOVIL"]) | (CollectionPhone.phone_type == None)
        )
        phones = db.execute(stmt).scalars().all()
        
        updated = 0
        for phone in phones:
            new_type = None
            if phone.phone_type:
                new_type = normalize_type_string(phone.phone_type)
            
            # Si el string no fue reconocido o era None, intentamos inferirlo del número de teléfono
            if not new_type and phone.phone_number:
                inferred = infer_phone_type(phone.phone_number)
                if inferred:
                    new_type = inferred
                    
            if new_type and new_type != phone.phone_type:
                phone.phone_type = new_type
                updated += 1

        db.commit()
        print(f"✅ Se actualizaron y corrigieron {updated} registros de teléfonos a 'FIJO' o 'MOVIL'.")
    except Exception as e:
        db.rollback()
        print(f"❌ Error al actualizar los teléfonos: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    main()
