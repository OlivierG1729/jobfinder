import os
import requests
import streamlit as st

API_BASE = os.getenv("API_BASE", "http://localhost:8000")

st.set_page_config(page_title="CSP Job Search", page_icon="🔎")
st.title("🔎 Rechercher des offres – Choisir le Service Public")

# --- Formulaire de recherche ---
with st.form("search_form"):
    q = st.text_input("Mots-clés (ex: data scientist, enseignant, juriste...)")
    page_size = st.number_input("Taille de page", 10, 200, 50, step=10)
    submitted = st.form_submit_button("Rechercher")

if submitted:
    try:
        resp = requests.post(
            f"{API_BASE}/search",
            json={"q": q, "page_size": page_size},
            timeout=30,
        )
        if resp.status_code != 200:
            st.error(resp.json().get("detail", "Erreur inconnue"))
        data = resp.json()["items"]

        st.success(f"{len(data)} résultat(s) trouvé(s)")

        for item in data:
            st.markdown(
                f"""**{item['title']}**
                {item.get('date') or ''}
                {item.get('url') or ''}"""
            )

    except Exception as e:
        st.error(str(e))

# --- Sauvegarde d'une recherche ---
st.divider()
st.subheader("🔔 Sauvegarder une recherche et recevoir des notifications")

with st.form("save_form"):
    q2 = st.text_input("Mots-clés à surveiller", key="q2")
    email = st.text_input(
        "Email pour les alertes (optionnel si vous utilisez ntfy)", key="email"
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
            st.error(resp.json().get("detail", "Erreur inconnue"))
        st.success("Recherche sauvegardée !")
    except Exception as e:
        st.error(str(e))

# --- Liste des recherches sauvegardées ---
if st.button("Voir recherches sauvegardées"):
    try:
        resp = requests.get(f"{API_BASE}/saved_searches", timeout=30)
        st.json(resp.json())
    except Exception as e:
        st.error(str(e))
