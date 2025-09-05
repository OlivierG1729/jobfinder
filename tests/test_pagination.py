import backend.service as service


PAGES = {
    1: [
        {"id": "1", "title": "A", "date": "2024-01-03"},
        {"id": "2", "title": "B", "date": "2024-01-02"},
    ],
    2: [
        {"id": "2", "title": "B bis", "date": "2024-01-02"},  # duplicate
        {"id": "3", "title": "C", "date": "2024-01-01"},
    ],
    3: [
        {"id": "4", "title": "D", "date": "2023-12-31"},
        {"id": "5", "title": "E", "date": "2023-12-30"},
    ],
}


def fake_fetch_api_page(query: str, page: int, per_page: int):
    items = list(PAGES.get(page, []))
    max_page = max(PAGES)
    if page < max_page:
        # pad to per_page to simulate presence of next page
        filler_count = max(0, per_page - len(items))
        for i in range(filler_count):
            items.append(
                {
                    "id": f"dummy-{page}-{i}",
                    "title": "X",
                    "date": "2000-01-01",
                }
            )
    return items


def test_limit(monkeypatch):
    service._SEARCH_CACHE.clear()
    monkeypatch.setattr(service, "_fetch_api_page", fake_fetch_api_page)
    results = service.search_offers("analyste", limit=5)
    assert len(results) == 5
    ids = [service.extract_offer_id(o) for o in results]
    assert len(set(ids)) == 5
    dates = [service.extract_date(o) for o in results]
    assert dates == sorted(dates, reverse=True)

