"""
Module envoi email via Microsoft 365 (Microsoft Graph, OAuth client_credentials).

Reutilise l'app registration Entra deja en place pour le module RH / parc auto
(meme tenant). Variables d'env : GRAPH_TENANT_ID, GRAPH_CLIENT_ID,
GRAPH_CLIENT_SECRET, GRAPH_FROM (boite expeditrice), GRAPH_FROM_NAME (optionnel).

Genere un HTML coloré avec :
- Section "Nouveautés du jour" (AO scrapes pour la 1ere fois)
- Section "VERTS encore actifs" (rappels score>=60, statut a_etudier, deadline <=14j)
"""
import os
import json
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime
from html import escape


def _get_graph_token(tenant: str, client_id: str, client_secret: str) -> str:
    """Jeton app-only via OAuth client_credentials (scope Graph .default)."""
    data = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials",
    }).encode("utf-8")
    req = urllib.request.Request(
        url=f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        tok = json.loads(resp.read().decode("utf-8"))
    access_token = tok.get("access_token")
    if not access_token:
        raise RuntimeError(f"token Graph: {str(tok.get('error_description') or tok)[:160]}")
    return access_token


def _send_via_graph(token: str, sender: str, sender_name: str,
                    to_addresses: list, subject: str, html: str,
                    cc_addresses: list = None) -> None:
    """POST /users/{sender}/sendMail. Graph renvoie 202 sans corps si OK."""
    message = {
        "subject": subject,
        "body": {"contentType": "HTML", "content": html},
        "from": {"emailAddress": {"name": sender_name, "address": sender}},
        "toRecipients": [{"emailAddress": {"address": a}} for a in to_addresses],
    }
    if cc_addresses:
        message["ccRecipients"] = [{"emailAddress": {"address": a}} for a in cc_addresses]
    payload = json.dumps({"message": message, "saveToSentItems": False}).encode("utf-8")
    req = urllib.request.Request(
        url=f"https://graph.microsoft.com/v1.0/users/{urllib.parse.quote(sender)}/sendMail",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        if resp.status != 202:
            raise RuntimeError(f"Graph sendMail status {resp.status}")


def envoyer_graph_simple(to_addresses, subject, html, cc_addresses=None):
    """Envoi Graph autonome (sujet + HTML fournis), reutilise l'app Entra (env GRAPH_*).
    Retourne {'sent': bool, 'reason': str}. N'emet jamais d'exception."""
    tenant = os.environ.get("GRAPH_TENANT_ID")
    client_id = os.environ.get("GRAPH_CLIENT_ID")
    client_secret = os.environ.get("GRAPH_CLIENT_SECRET")
    sender = os.environ.get("GRAPH_FROM")
    sender_name = os.environ.get("GRAPH_FROM_NAME") or "Veille AO Neurones"
    missing = [k for k, v in {
        "GRAPH_TENANT_ID": tenant,
        "GRAPH_CLIENT_ID": client_id,
        "GRAPH_CLIENT_SECRET": client_secret,
        "GRAPH_FROM": sender,
    }.items() if not v]
    if missing:
        return {"sent": False, "reason": f"Config Graph manquante : {', '.join(missing)}"}
    try:
        token = _get_graph_token(tenant, client_id, client_secret)
        _send_via_graph(token, sender, sender_name, to_addresses, subject, html, cc_addresses)
        return {"sent": True, "reason": "OK"}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return {"sent": False, "reason": f"HTTP {e.code}: {body[:300]}"}
    except Exception as e:
        return {"sent": False, "reason": f"{type(e).__name__}: {e}"}


def _color_score(score: int) -> str:
    if score >= 60:
        return "#107C41"  # vert fonce
    if score >= 35:
        return "#B7472A"  # orange-jaune fonce
    return "#666666"


def _bg_score(score: int) -> str:
    if score >= 60:
        return "#C6EFCE"
    if score >= 35:
        return "#FFEB9C"
    return "#F2F2F2"


def _row_html(ao: dict) -> str:
    """Genere une ligne <tr> d'un AO."""
    score = ao.get("score", 0)
    bg = _bg_score(score)
    color = _color_score(score)
    objet = escape(ao.get("objet", ""))[:300]
    acheteur = escape(ao.get("acheteur", ""))[:120]
    lieu = escape(ao.get("lieu_execution", ""))[:60]
    ref = escape(ao.get("reference_ao", ""))
    cat = escape(ao.get("categorie", ""))
    dl = escape(ao.get("date_limite", ""))
    heure = escape(ao.get("heure_limite", ""))
    lien = escape(ao.get("lien_fiche", "#"))

    return f"""
    <tr>
      <td style="background:{bg};color:{color};font-weight:bold;text-align:center;padding:8px;border:1px solid #ddd;font-size:18px;">{score}</td>
      <td style="padding:8px;border:1px solid #ddd;font-size:13px;"><strong>{ref}</strong><br><span style="color:#666;font-size:11px;">{cat}</span></td>
      <td style="padding:8px;border:1px solid #ddd;font-size:13px;">{objet}</td>
      <td style="padding:8px;border:1px solid #ddd;font-size:12px;">{acheteur}</td>
      <td style="padding:8px;border:1px solid #ddd;font-size:12px;text-align:center;">{lieu}</td>
      <td style="padding:8px;border:1px solid #ddd;font-size:12px;text-align:center;white-space:nowrap;"><strong>{dl}</strong><br>{heure}</td>
      <td style="padding:8px;border:1px solid #ddd;text-align:center;"><a href="{lien}" style="background:#1F4E78;color:white;padding:6px 10px;text-decoration:none;border-radius:3px;font-size:11px;">Ouvrir</a></td>
    </tr>
    """


def _section_html(titre: str, aos: list, vide_message: str = None) -> str:
    if not aos:
        if vide_message:
            return f'<h2 style="color:#1F4E78;margin-top:30px;">{escape(titre)}</h2><p style="color:#666;font-style:italic;">{escape(vide_message)}</p>'
        return ""

    rows = "".join(_row_html(ao) for ao in aos)
    return f"""
    <h2 style="color:#1F4E78;margin-top:30px;border-bottom:2px solid #1F4E78;padding-bottom:5px;">{escape(titre)} <span style="color:#888;font-size:14px;font-weight:normal;">({len(aos)})</span></h2>
    <table style="width:100%;border-collapse:collapse;margin-top:10px;">
      <thead>
        <tr style="background:#1F4E78;color:white;">
          <th style="padding:8px;font-size:12px;">Score</th>
          <th style="padding:8px;font-size:12px;">Reference</th>
          <th style="padding:8px;font-size:12px;text-align:left;">Objet</th>
          <th style="padding:8px;font-size:12px;text-align:left;">Acheteur</th>
          <th style="padding:8px;font-size:12px;">Lieu</th>
          <th style="padding:8px;font-size:12px;">Date limite</th>
          <th style="padding:8px;font-size:12px;">Action</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
    """


def construire_email_html(nouveautes: list, rappels: list, run_id: str = "") -> str:
    """Construit le corps HTML complet de l'email."""
    nouveautes = sorted(nouveautes, key=lambda x: x.get("score", 0), reverse=True)
    rappels = sorted(rappels, key=lambda x: x.get("score", 0), reverse=True)

    nb_verts_nouveaux = sum(1 for a in nouveautes if a.get("score", 0) >= 60)
    nb_jaunes_nouveaux = sum(1 for a in nouveautes if 35 <= a.get("score", 0) < 60)

    header = f"""
    <div style="font-family: Calibri, Arial, sans-serif; max-width: 1100px; margin: 0 auto; padding: 20px;">
      <h1 style="color:#1F4E78;border-bottom:3px solid #1F4E78;padding-bottom:8px;">Veille AO Neurones Technologies</h1>
      <p style="color:#555;">Rapport genere le <strong>{datetime.now().strftime('%d/%m/%Y a %H:%M')}</strong>{f' (run {run_id})' if run_id else ''}.</p>
      <div style="background:#F2F2F2;padding:12px;border-radius:5px;margin:15px 0;">
        <strong>Resume :</strong>
        {nb_verts_nouveaux} VERTS nouveaux, {nb_jaunes_nouveaux} JAUNES nouveaux, {len(rappels)} VERTS encore actifs (rappel).
      </div>
    """

    section_nouveautes = _section_html(
        "Nouveautes du jour",
        nouveautes,
        vide_message="Aucune nouveaute depuis le dernier scrape."
    )

    section_rappels = _section_html(
        "VERTS encore actifs (deadline proche)",
        rappels,
        vide_message=None  # pas affiche si vide (sauf nouveautes vides aussi)
    )

    if not nouveautes and not rappels:
        body = '<p style="color:#666;font-style:italic;padding:20px;background:#FFFAE6;border-left:4px solid #F0A800;">Aucun nouvel AO a signaler depuis le dernier scrape, et aucun VERT actif avec deadline proche. Le systeme tourne normalement.</p>'
    else:
        body = section_nouveautes + section_rappels

    footer = """
      <hr style="margin-top:40px;border:0;border-top:1px solid #ddd;">
      <p style="color:#999;font-size:11px;text-align:center;">
        Email automatique - Veille AO marchespublics.gov.ma<br>
        Configuration : config.json - Repository : github.com/najikarim66/neurones-veille-ao
      </p>
    </div>
    """

    return header + body + footer


def envoyer_email(
    config_email: dict,
    nouveautes: list,
    rappels: list,
    run_id: str = "",
) -> dict:
    """
    Envoie l'email via Microsoft 365 (Microsoft Graph, app-only).

    Retourne {'sent': bool, 'message_id': str|None, 'reason': str}.

    Decision d'envoi :
    - Si nouveautes >0 OU rappels >0 : envoie toujours
    - Si tout est vide :
        - matin (heure < 12) + envoyer_meme_si_zero_nouveaute_matin = true → envoie
        - apres-midi + envoyer_meme_si_zero_nouveaute_apres_midi = true → envoie
        - sinon : skip
    """
    tenant = os.environ.get("GRAPH_TENANT_ID")
    client_id = os.environ.get("GRAPH_CLIENT_ID")
    client_secret = os.environ.get("GRAPH_CLIENT_SECRET")
    sender = os.environ.get("GRAPH_FROM") or config_email.get("from_address")
    sender_name = os.environ.get("GRAPH_FROM_NAME") or config_email.get("from_name", "Veille AO Neurones")
    missing = [k for k, v in {
        "GRAPH_TENANT_ID": tenant,
        "GRAPH_CLIENT_ID": client_id,
        "GRAPH_CLIENT_SECRET": client_secret,
        "GRAPH_FROM": sender,
    }.items() if not v]
    if missing:
        return {"sent": False, "message_id": None, "reason": f"Config Graph manquante : {', '.join(missing)}"}

    # Logique d'envoi
    is_morning = datetime.now().hour < 12
    has_content = bool(nouveautes) or bool(rappels)
    if not has_content:
        if is_morning and not config_email.get("envoyer_meme_si_zero_nouveaute_matin", True):
            return {"sent": False, "message_id": None, "reason": "Pas de contenu, skip matin"}
        if (not is_morning) and not config_email.get("envoyer_meme_si_zero_nouveaute_apres_midi", False):
            return {"sent": False, "message_id": None, "reason": "Pas de contenu, skip apres-midi"}

    # Sujet
    nb_verts = sum(1 for a in nouveautes if a.get("score", 0) >= 60)
    if has_content:
        if nb_verts > 0:
            subj = f"{config_email['subject_prefix']} {nb_verts} VERT(S) nouveau(x) - {datetime.now().strftime('%d/%m/%Y')}"
        else:
            subj = f"{config_email['subject_prefix']} {len(nouveautes)} nouveau(x) AO - {datetime.now().strftime('%d/%m/%Y')}"
    else:
        subj = f"{config_email['subject_prefix']} Aucun nouvel AO - {datetime.now().strftime('%d/%m/%Y')}"

    html = construire_email_html(nouveautes, rappels, run_id=run_id)

    try:
        token = _get_graph_token(tenant, client_id, client_secret)
        _send_via_graph(token, sender, sender_name, config_email["to_addresses"], subj, html)
        return {"sent": True, "message_id": "Graph/202", "reason": "OK"}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return {"sent": False, "message_id": None, "reason": f"HTTP {e.code}: {body[:300]}"}
    except Exception as e:
        return {"sent": False, "message_id": None, "reason": f"{type(e).__name__}: {e}"}
