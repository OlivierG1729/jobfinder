# CSP Job Search – Skeleton

Une petite appli Python pour rechercher les fiches de poste de **choisirleservicepublic.fr** via la **Tabular API** de data.gouv.fr,
classer par ordre chronologique et **notifier** lorsqu'une nouvelle offre correspondant à une recherche apparaît.

## Contenu
- `backend/` : API FastAPI + scheduler (APScheduler) + SQLite
- `frontend/` : mini interface Streamlit
- `.env.example` : variables d'environnement (RID Data.gouv, SMTP, NTFY)
- `requirements.txt`

## Démarrage rapide

1) **Cloner / extraire** ce dossier puis copier `.env.example` en `.env` et **renseigner** au moins :
   - `RID` : l'UUID de la ressource (CSV) des offres CSP sur data.gouv.fr (ex. `73f35aaa-15a2-4ddb-8be1-0a650e65fd7d`)
   - Optionnel pour notifications :
       - Via email SMTP : `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `MAIL_FROM`
       - Via **ntfy.sh** (push) : `NTFY_URL` (ex. `https://ntfy.sh/mon-topic-secret`)

2) **Installer**
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

3) **Lancer le backend (API + scheduler)** :
```bash
uvicorn backend.main:app --reload --port 8000
```

4) **Lancer l'UI Streamlit** :
```bash
streamlit run frontend/streamlit_app.py
```

5) **Tester la recherche** : dans l'UI, entrer des mots-clés, vérifier l'ordre (plus récent -> plus ancien), sauvegarder la recherche + email.
Le scheduler (dans le backend) vérifie périodiquement et envoie une notification lorsqu'une **nouvelle** offre apparaît.

---

## Notes importantes

- **Colonnes** : Par défaut, on suppose : `id` (identifiant), `intitule` (titre), `datePublication` (date), `url` (lien).  
  Si l'API renvoie d'autres noms, adaptez `COLUMN_*` dans `backend/main.py`. Pour voir le schéma, visitez:
  `https://tabular-api.data.gouv.fr/api/resources/<RID>/profile/`

- **Tri** : effectué côté API via `datePublication__sort=desc` (adapter si le champ diffère).

- **Fréquence** : La Tabular API CSP est mise à jour **hebdomadairement** ; pour de l'alerte quasi temps réel, vous pouvez compléter par un scrutateur du site (non inclus ici).

- **Sécurité & RGPD** : si vous stockez des emails, veillez à les protéger et à informer les utilisateurs.

Bon hack !
