
import requests

resp = requests.post(
    "http://127.0.0.1:8001/search",
    json={"q": "analyste", "page_size": 50, "page": 1},
    timeout=30,
)
print(resp.status_code)
print(resp.json())
