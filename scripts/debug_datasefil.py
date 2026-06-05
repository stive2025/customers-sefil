import os
import requests
import json
from pathlib import Path

def main():
    import dotenv
    dotenv.load_dotenv(Path(__file__).parent.parent / ".env")
    url = os.getenv("DATASEFIL_API_URL", "https://api.sefil.com.ec/api/client/identification")
    token = os.getenv("DATASEFIL_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    try:
        resp = requests.get(f"{url}/0702743030", headers=headers)
        print(json.dumps(resp.json(), indent=2))
    except Exception as exc:
        print(exc)

if __name__ == "__main__":
    main()
