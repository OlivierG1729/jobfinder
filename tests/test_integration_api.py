import pytest
import requests

from backend import service


def test_faulty_query_returns_many_offers():
    try:
        results = service.search_offers("dats scientist", limit=40, refresh_cache=True)
    except (RuntimeError, requests.exceptions.RequestException) as exc:
        pytest.skip(f"API unreachable: {exc}")
    assert len(results) > 20
