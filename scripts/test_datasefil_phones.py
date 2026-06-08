import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.etl_datasefil import prepare_datasefil_customers

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
    result = prepare_datasefil_customers(raw_data)
    for r in result:
        print(r.model_dump_json(indent=2))

if __name__ == "__main__":
    main()
