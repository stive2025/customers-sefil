import json
from app.core.database import SessionLocal
from app.services.etl_collecta import sync_collecta_data

def run():
    print("🚀 Iniciando el proceso ETL de Collecta...")
    
    # 1. Extraer (Extract): Obtenemos los datos. 
    # NOTA: Aquí es donde más adelante reemplazarás el open() por tu petición real con requests.get("URL_DE_COLLECTA")
    try:
        with open("mock_collecta.json", "r", encoding="utf-8") as file:
            raw_data = json.load(file)
        print(f"📥 Se obtuvieron {len(raw_data)} registros de la fuente.")
    except FileNotFoundError:
        print("❌ Error: No se encontró el archivo mock_collecta.json")
        return

    # 2. Transformar y Cargar (Transform & Load)
    db = SessionLocal()
    try:
        print("⚙️  Limpiando datos y guardando en PostgreSQL...")
        
        # Llamamos a la función que te generó Claude
        resultado = sync_collecta_data(raw_data, db)
        
        print("\n✅ Proceso completado. Resumen:")
        print(f"   🔹 Nuevos clientes creados: {resultado.created}")
        print(f"   🔹 Clientes actualizados:   {resultado.updated}")
        print(f"   🔹 Registros omitidos:      {resultado.skipped}")
        
    except Exception as e:
        print(f"\n❌ Ocurrió un error en la base de datos: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    run()