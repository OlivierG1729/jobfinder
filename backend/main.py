# backend/main.py
from __future__ import annotations

from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

try:
    from dotenv import load_dotenv  # type: ignore

    ROOT = Path(__file__).resolve().parents[1]
    load_dotenv(dotenv_path=ROOT / ".env", override=True)
except Exception:
    pass

from .db import init_db, get_conn
from .scheduler import start_scheduler
from .service import (
    search_offers,           # ✅ c'est la seule fonction de recherche à utiliser
    extract_offer_id,
    extract_title,
    extract_date,
    extract_url,
)

app = FastAPI(title="CSP Job Search API", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SearchQuery(BaseModel):
    q: Optional[str] = None
    page_size: int = 50
    page: int = 1


class SaveSearch(BaseModel):
    q: str
    email: Optional[str] = None


@app.on_event("startup")
def on_startup():
    init_db()
    start_scheduler()


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"ok": True}


@app.post("/search")
def post_search(body: SearchQuery) -> Dict[str, Any]:
    """
    Appelle la recherche distante et renvoie une liste normalisée.
    """
    try:
        offers = search_offers(query=body.q, page_size=body.page_size, page=body.page)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    result = []
    for o in offers:
        result.append(
            {
                "id": extract_offer_id(o) if isinstance(o, dict) else None,
                "title": extract_title(o) if isinstance(o, dict) else "",
                "date": extract_date(o) if isinstance(o, dict) else None,
                "url": extract_url(o) if isinstance(o, dict) else None,
                "raw": o,
            }
        )
    # pas de total fiable côté site -> on expose seulement la page actuelle
    return {"items": result, "page": body.page, "page_size": body.page_size}


@app.post("/save_search")
def save_search(body: SaveSearch) -> Dict[str, Any]:
    con = get_conn()
    try:
        cur = con.cursor()
        cur.execute(
            "INSERT INTO saved_searches(query, email) VALUES (?, ?)",
            (body.q, body.email),
        )
        con.commit()
    finally:
        con.close()
    return {"ok": True}


@app.get("/saved_searches")
def list_saved() -> Dict[str, List[Dict[str, Any]]]:
    con = get_conn()
    try:
        cur = con.cursor()
        rows = cur.execute(
            "SELECT id, query, email FROM saved_searches ORDER BY id DESC"
        ).fetchall()
        items = [{"id": r[0], "query": r[1], "email": r[2]} for r in rows]
    finally:
        con.close()
    return {"items": items}
