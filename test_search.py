import requests

if __name__ == "__main__":
    resp = requests.post(
        "http://127.0.0.1:8001/search",
        # ``limit`` replaces the old pagination params and is capped at 1000
        json={"q": "analyste", "limit": 50},
        timeout=30,
    )
    print(resp.status_code)
    print(resp.json())
