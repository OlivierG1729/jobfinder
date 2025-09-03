# frontend/streamlit_app.py
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests
import streamlit as st

API_BASE = os.getenv("API_BASE", "http://localhost:8000")

st.set_page_config(page_title="CSP Job Search", page_icon="🔎", layout="wide")
st.title("🔎 Rechercher des offres – Choisir le Service Public")

# -----------------------------
# Helpers
# -----------------------------
def fmt_date(iso_str: Optional[str]) -> str:
    """Affiche une date ISO en JJ/MM/AAAA. Si parsing impossible, retourne la chaîne brute."""
    if not iso_str:
        return ""
    try:
        s = iso_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt.strftime("%d/%m/%Y")
    except Exception:
        return iso_str

def call_api_search(q: Optional[str], n: int) -> Dict[str, Any]:
    """Appelle /search du backend et renvoie le payload JSON."""
    resp = requests.post(
        f"{API_BASE}/search",
        json={"q": q or None, "limit": int(n)},
        timeout=30,
    )
    if resp.status_code != 200:
        try:
            detail = resp.json().get("detail", f"HTTP {resp.status_code}")
        except Exception:
            detail = f"HTTP {resp.status_code}"
        raise RuntimeError(f"Recherche échouée : {detail}")
    return resp.json()

# -----------------------------
# État initial
# -----------------------------
if "q" not in st.session_state:
    st.session_state.q = "analyste"
if "n" not in st.session_state:
    st.session_state.n = 50

# -----------------------------
# Formulaire
# -----------------------------
with st.form("search_form"):
    q_in = st.text_input(
        "Mots-clés",
        value=st.session_state.q,
        help="Exemples : data scientist, enseignant, juriste, développeur…",
    )
    n_in = st.number_input(
        "Nombre d’offres",
        min_value=1,
        max_value=1000,
        value=st.session_state.n,
        step=1,
    )
    submitted = st.form_submit_button("Rechercher")

if submitted:
    st.session_state.q = q_in.strip()
    st.session_state.n = int(n_in)

# -----------------------------
# Affichage résultats
# -----------------------------
def render_results() -> None:
    try:
        payload = call_api_search(
            q=st.session_state.q,
            n=st.session_state.n,
        )
        items: List[Dict[str, Any]] = payload.get("items", [])
        total_est = payload.get("total_estimated")

        if total_est:
            st.caption(f"~{total_est:,} offre(s) au total (estimation)".replace(",", " "))

        st.success(f"{len(items)} résultat(s)")

        if not items:
            st.info(
                "Aucun résultat. Essaie avec d'autres mots-clés. "
                "Le backend utilise l’API officielle CSP et bascule sur un fallback HTML si besoin."
            )

        for it in items:
            title = it.get("title") or "Offre"
            url = it.get("url") or ""
            date_txt = fmt_date(it.get("date"))
            with st.container(border=True):
                st.markdown(f"**{title}**")
                meta_parts = []
                if date_txt:
                    meta_parts.append(f"📅 {date_txt}")
                if url:
                    meta_parts.append(f"[Voir l’offre]({url})")
                if meta_parts:
                    st.caption(" · ".join(meta_parts))
    except Exception as e:
        st.error(str(e))
        st.info(
            "Astuce : vérifie que le backend FastAPI tourne bien sur "
            f"{API_BASE} (ex.: `uvicorn backend.main:app --reload --port 8000`)."
        )

render_results()
st.divider()
st.subheader("🔔 Sauvegarder une recherche et recevoir des notifications")

# -----------------------------
# Sauvegarde d'une recherche
# -----------------------------
with st.form("save_form"):
    q2 = st.text_input("Mots-clés à surveiller", key="q2")
    email = st.text_input(
        "Email pour les alertes (optionnel si vous utilisez ntfy)",
        key="email",
        help="Laissez vide si vous n'utilisez pas d'email. Vous pouvez aussi configurer NTFY côté serveur.",
    )
    saved = st.form_submit_button("Sauvegarder")

if saved:
    try:
        resp = requests.post(
            f"{API_BASE}/save_search",
            json={"q": q2, "email": email or None},
            timeout=30,
        )
        if resp.status_code != 200:
            try:
                st.error(resp.json().get("detail", f"HTTP {resp.status_code}"))
            except Exception:
                st.error(f"HTTP {resp.status_code}")
        else:
            st.success("Recherche sauvegardée !")
    except Exception as e:
        st.error(str(e))

# -----------------------------
# Liste des recherches sauvegardées
# -----------------------------
if st.button("Voir recherches sauvegardées"):
    try:
        resp = requests.get(f"{API_BASE}/saved_searches", timeout=30)
        if resp.status_code != 200:
            try:
                st.error(resp.json().get("detail", f"HTTP {resp.status_code}"))
            except Exception:
                st.error(f"HTTP {resp.status_code}")
        else:
            st.json(resp.json())
    except Exception as e:
        st.error(str(e))

with st.expander("Aide / Debug"):
    st.markdown(
        f"""
- **Backend API** attendu : `{API_BASE}`  
- Test rapide : ouvrez [`{API_BASE}/docs`]({API_BASE}/docs) dans votre navigateur pour vérifier que FastAPI tourne.  
- L'API backend interroge l’API officielle CSP et bascule sur un **fallback HTML** si besoin, en triant toujours par **date décroissante**.
"""
    )
