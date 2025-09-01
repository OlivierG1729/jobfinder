import requests

BASE = "https://choisirleservicepublic.gouv.fr/api/offres"

def _api_get(params):
    r = requests.get(BASE, params=params, timeout=30, headers={"Accept": "application/json"})
    r.raise_for_status()
    try:
        return r.json()
    except ValueError:
        raise ValueError(f"Réponse non‑JSON : {r.text[:200]!r}")

params = {"limit": 50, "page": 1, "q": "data scientist"}
data = _api_get(params)

