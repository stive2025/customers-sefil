import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.database import SessionLocal
from app.services.unified_sync import sync_external_customer

payload = {
    "identification": "0702743030",
    "name": "ALVARADO TORRES TERESA TRINIDAD",
    "contacts": [
      {
        "phone_number": "0980297248",
        "phone_type": "actualizado"
      }
    ]
}

def main():
    db = SessionLocal()
    try:
        res = sync_external_customer(db=db, payload=payload, source="DATA SEFIL")
        print("Success!", res.id)
    except Exception as e:
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    main()
