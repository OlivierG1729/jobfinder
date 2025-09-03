import backend.service as service

def fake_fetch_list_page(query: str, page: int):
    pages = {
        1: ([
            {"id": "1", "title": "A", "date": "3 Jan 2024"},
            {"id": "2", "title": "B", "date": "2 Jan 2024"},
        ], True),
        2: ([
            {"id": "2", "title": "B bis", "date": "2 Jan 2024"},  # duplicate
            {"id": "3", "title": "C", "date": "1 Jan 2024"},
        ], True),
        3: ([
            {"id": "4", "title": "D", "date": "31 Dec 2023"},
            {"id": "5", "title": "E", "date": "30 Dec 2023"},
        ], False),
    }
    return pages.get(page, ([], False))

def test_pagination_no_overlap(monkeypatch):
    monkeypatch.setattr(service, "_fetch_list_page", fake_fetch_list_page)
    page1 = service.search_offers("analyste", page_size=2, page=1)
    page2 = service.search_offers("analyste", page_size=2, page=2)
    ids1 = {service.extract_offer_id(o) for o in page1}
    ids2 = {service.extract_offer_id(o) for o in page2}
    assert ids1.isdisjoint(ids2)
