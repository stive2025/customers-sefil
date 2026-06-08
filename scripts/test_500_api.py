import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

payload = {
  "source": "DATA SEFIL",
  "data": {
    "identification": "0702743030",
    "name": "ALVARADO TORRES TERESA TRINIDAD",
    "contacts": [
      {
        "phone_number": "0980297248",
        "phone_type": "actualizado"
      }
    ]
  }
}

# The endpoint is protected by API key?
headers = {"X-API-Key": "sk_live_collecta_9x8A2"}

def main():
    response = client.post("/api/v1/sync/customer", json=payload, headers=headers)
    print("Status code:", response.status_code)
    print("Response body:", response.text)

if __name__ == "__main__":
    main()
