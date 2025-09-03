from unittest.mock import patch

from backend import service


def test_fast_mode_calls_fetch_once():
    query = "dummy"
    with patch("backend.service._fetch_list_page", return_value=([], False)) as mock_fetch:
        service.search_offers(query=query, page=3, fast_mode=True)
        mock_fetch.assert_called_once_with(query, 3)
