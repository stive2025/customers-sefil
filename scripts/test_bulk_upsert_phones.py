import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.database import SessionLocal
from app.models.customer import Customer
from app.services.etl_datasefil import prepare_datasefil_customers
from app.services.bulk_upsert import bulk_upsert_customers

raw_data = [
    {
      "id": 78012,
      "identification": "0702743030",
      "uses_parent_identification": 0,
      "parent_identification": None,
      "name": "ALVARADO TORRES TERESA TRINIDAD",
      "email": "psrionegro07d06santarosa@gmail.com",
      "micro_activa": None,
      "birth": "1971-06-06",
      "death": None,
      "gender": "FEMENINO",
      "state_civil": "CASADO",
      "economic_activity": None,
      "economic_area": None,
      "nationality": "ECUATORIANA",
      "profession": "QUEHACER. DOMESTICOS",
      "place_birth": "EL ORO/SANTA ROSA/SANTA ROSA",
      "salary": 0,
      "contacts": [
        {
          "id": 40133,
          "phone_number": "0980297248",
          "phone_type": "actualizado",
          "counter_correct_number": 0,
          "counter_incorrect_number": 0,
          "client_id": 78012,
          "source": "datasefil"
        },
        {
          "id": 40134,
          "phone_number": "0939526084",
          "phone_type": "actualizado",
          "counter_correct_number": 0,
          "counter_incorrect_number": 0,
          "client_id": 78012,
          "source": "datasefil"
        },
        {
          "id": 40136,
          "phone_number": "958700357",
          "phone_type": "actualizado",
          "counter_correct_number": 0,
          "counter_incorrect_number": 0,
          "client_id": 78012,
          "source": "datasefil"
        }
      ]
    }
]

def main():
    items = prepare_datasefil_customers(raw_data)
    print("Prepared items phones:", len(items[0].phones))
    
    db = SessionLocal()
    try:
        res = bulk_upsert_customers(items, db)
        print("Upsert result:", res.model_dump())
        
        # Verify in DB
        customer = db.query(Customer).filter_by(identification="0702743030").first()
        print("DB phones count:", len(customer.phones))
        for p in customer.phones:
            print(" -", p.phone_number, p.phone_type, p.is_active)
    finally:
        db.close()

if __name__ == "__main__":
    main()
