import sys
from pathlib import Path

# Agregar la raíz del proyecto al sys.path para poder importar módulos de la app
sys.path.append(str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, update
from app.core.database import SessionLocal
from app.models.collections import CollectionPhone, CollectionAddress, CollectionEmail
from app.models.relationships import CustomerRelationship

def main():
    db = SessionLocal()
    try:
        # 1. Actualizar created_source de "collapi" a "Collecta"
        models_with_source = [
            CollectionPhone,
            CollectionAddress,
            CollectionEmail,
            CustomerRelationship
        ]
        
        updated_sources = 0
        for model in models_with_source:
            # Check if the model has 'created_source'
            if hasattr(model, 'created_source'):
                stmt = update(model).where(model.created_source == "collapi").values(created_source="Collecta")
                result = db.execute(stmt)
                updated_sources += result.rowcount
                
        # 2. Actualizar address_type de "JOB" a "Trabajo" y "HOME" a "Hogar"
        stmt_job = update(CollectionAddress).where(CollectionAddress.address_type == "JOB").values(address_type="Trabajo")
        result_job = db.execute(stmt_job)
        
        stmt_home = update(CollectionAddress).where(CollectionAddress.address_type == "HOME").values(address_type="Hogar")
        result_home = db.execute(stmt_home)

        db.commit()
        
        print(f"✅ Se actualizaron {updated_sources} registros cambiando la fuente 'collapi' a 'Collecta'.")
        print(f"✅ Se actualizaron {result_job.rowcount} direcciones de 'JOB' a 'Trabajo'.")
        print(f"✅ Se actualizaron {result_home.rowcount} direcciones de 'HOME' a 'Hogar'.")
        
    except Exception as e:
        db.rollback()
        print(f"❌ Error al ejecutar las actualizaciones: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    main()
