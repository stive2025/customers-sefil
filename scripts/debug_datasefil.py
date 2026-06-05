import os
import requests
import json
from pathlib import Path

def main():
    import dotenv
    dotenv.load_dotenv(Path(__file__).parent.parent / ".env")
    url = os.getenv("DATASEFIL_API_URL", "http://172.20.1.105:8000/api/clients")
    token = os.getenv("DATASEFIL_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    try:
        resp = requests.get(url, headers=headers, params={"identification": "0702743030"})
        print(json.dumps(resp.json(), indent=2))
    except Exception as exc:
        print(exc)

if __name__ == "__main__":
    main()
