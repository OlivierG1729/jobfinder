import os, time, requests
from apscheduler.schedulers.background import BackgroundScheduler
from email.message import EmailMessage
import smtplib
from .db import get_conn
from .service import search_offers, extract_offer_id, extract_date, extract_title, extract_url

SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
MAIL_FROM = os.getenv("MAIL_FROM", "bot@example.com")

NTFY_URL = os.getenv("NTFY_URL")

def send_email(to_addr: str, subject: str, html: str):
    if not (SMTP_HOST and SMTP_USER and SMTP_PASS and to_addr):
        return
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = MAIL_FROM
    msg["To"] = to_addr
    msg.set_content("Nouvelles offres détectées.")
    msg.add_alternative(html, subtype="html")
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
        s.starttls()
        s.login(SMTP_USER, SMTP_PASS)
        s.send_message(msg)

def send_ntfy(title: str, message: str):
    if not NTFY_URL:
        return
    try:
        requests.post(NTFY_URL, data=message.encode("utf-8"), headers={"Title": title}, timeout=15)
    except Exception:
        pass

def check_once():
    con = get_conn(); cur = con.cursor()
    for (query, email) in cur.execute("SELECT query, email FROM saved_searches"):
        offers = search_offers(query=query, limit=50)
        # Load seen into set
        cur2 = con.cursor()
        cur2.execute("SELECT offer_id FROM seen")
        seen_ids = {row[0] for row in cur2.fetchall()}
        new_items = []
        for off in offers:
            oid = extract_offer_id(off)
            if not oid or oid in seen_ids:
                continue
            new_items.append(off)
            cur2.execute("INSERT OR IGNORE INTO seen(offer_id) VALUES (?)", (oid,))
        con.commit()
        if new_items:
            items_html = []
            for o in new_items:
                items_html.append(f'<li><a href="{extract_url(o) or "#"}">{extract_title(o)}</a> – {extract_date(o) or ""}</li>')
            html = "<ul>" + "".join(items_html) + "</ul>"
            subj = f"{len(new_items)} nouvelle(s) offre(s) pour « {query} »"
            send_email(email, subj, html)
            send_ntfy(subj, "\n".join([f"{extract_title(o)} — {extract_url(o) or ''}" for o in new_items]))
    con.close()

def start_scheduler():
    minutes = int(os.getenv("SCHED_MINUTES", "120"))
    sch = BackgroundScheduler()
    sch.add_job(check_once, "interval", minutes=minutes, id="csp_check", replace_existing=True)
    sch.start()
