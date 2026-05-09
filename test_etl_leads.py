import os
from dotenv import load_dotenv
from app.core.database import SessionLocal
from app.services.etl_leads import sync_leads_data

def run():
    print("🚀 Iniciando el proceso ETL de Enriquecimiento (Leads MySQL)...")
    
    # 1. Cargar las variables de entorno (Asegúrate de tener instalado python-dotenv: pip install python-dotenv)
    load_dotenv()
    
    # Validar que al menos el host esté configurado
    if not os.getenv("LEADS_DB_HOST"):
         print("❌ Error: No se encontraron las variables de entorno (ej. LEADS_DB_HOST).")
         print("Por favor, configúralas en tu archivo .env o en el sistema antes de ejecutar.")
         return

    db_central = SessionLocal()
    try:
        print("⚙️  Conectando a MySQL y fusionando datos en PostgreSQL...")
        
        # Llamamos a la función principal de Leads
        resultado = sync_leads_data(db_central)
        
        print("\n✅ Proceso completado. Resumen:")
        print("\n✅ Proceso completado. Resumen del objeto SyncResult:")
        print(resultado) # Imprime el objeto tal cual
        # Ojo: Adaptar estos nombres si la dataclass de Claude tiene variables distintas
        
    except Exception as e:
        print(f"\n❌ Ocurrió un error en el ETL: {e}")
        db_central.rollback()
    finally:
        db_central.close()

if __name__ == "__main__":
    run()