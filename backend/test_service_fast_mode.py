from unittest.mock import patch

from backend import service


def test_fast_mode_calls_fetch_once():
    query = "dummy"
    with patch("backend.service._fetch_api_page", return_value=[]) as mock_fetch:
        service.search_offers(query=query, fast_mode=True)
        mock_fetch.assert_called_once_with(query, 1, 50)
