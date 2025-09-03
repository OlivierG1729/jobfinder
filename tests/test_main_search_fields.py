from unittest.mock import patch

from backend.main import post_search, SearchQuery


def test_post_search_includes_org_logo():
    sample_offers = [
        {
            "id": "1",
            "title": "A",
            "date": "2024-01-01",
            "url": "http://example.com/a",
            "org": "Org A",
            "logo": "http://example.com/logo.png",
        }
    ]
    with patch("backend.main.search_offers", return_value=sample_offers):
        res = post_search(SearchQuery(q="test", limit=1))

    assert res["items"][0]["organization"] == "Org A"
    assert res["items"][0]["logo"] == "http://example.com/logo.png"

