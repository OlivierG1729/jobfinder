# CSP Job Search – Skeleton

Application Python légère pour rechercher les fiches de poste de **choisirleservicepublic.gouv.fr** via l’**API officielle** du site, classer les résultats par ordre chronologique et notifier lorsqu’une nouvelle offre correspond à une recherche sauvegardée.

## Contenu
- `backend/` : API FastAPI + scheduler (APScheduler) + SQLite  
- `frontend/` : mini interface Streamlit  
- `.env.example` : variables d’environnement pour notifications (SMTP, NTFY)  
- `requirements.txt`

## Démarrage rapide

1. **Cloner / extraire** ce dossier puis copier `.env.example` en `.env` et renseigner si besoin :
   - paramètres SMTP pour l’envoi d’e‑mails ;
   - ou une URL `NTFY_URL` pour les notifications push.

2. **Installer**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
