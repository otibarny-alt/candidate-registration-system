"""Read the active party brand from the central voting-system service."""
import json
import os
import re
import threading
import time
from urllib.request import Request, urlopen

import psycopg
from flask import jsonify


DEFAULT = {
    "code": "ODM",
    "name": "Orange Democratic Movement",
    "abbreviation": "ODM",
    "slogan": "Tuko Tayari",
    "membership_prefix": "ODM",
    "primary": "#ef7d00",
    "secondary": "#111111",
    "accent": "#fff2df",
    "header_url": "",
}
_CACHE = {"at": 0.0, "brand": dict(DEFAULT), "error": ""}
_LOCK = threading.Lock()


def branding_api_url():
    direct = os.getenv("PARTY_BRANDING_API_URL", "").strip()
    if direct:
        return direct
    base = (
        os.getenv("VOTING_SYSTEM_BASE_URL", "https://voting-simulation-system.onrender.com").strip()
        or os.getenv("VOTING_SIMULATION_ADMIN_URL", "").strip()
        or os.getenv("SIMULATION_BASE_URL", "").strip()
    ).rstrip("/")
    return base + "/api/party-branding" if base else ""


def get_brand(force=False):
    now = time.time()
    if not force and now - _CACHE["at"] < 10:
        return dict(_CACHE["brand"])
    with _LOCK:
        if not force and now - _CACHE["at"] < 10:
            return dict(_CACHE["brand"])
        value = dict(_CACHE["brand"] or DEFAULT)
        error = ""
        url = branding_api_url()
        if url:
            try:
                request = Request(
                    url,
                    headers={"Accept": "application/json", "User-Agent": "CandidatePortalBranding/1.0"},
                )
                with urlopen(request, timeout=5) as response:
                    data = json.loads(response.read().decode("utf-8"))
                remote = dict(data.get("brand") or {})
                value = {
                    **DEFAULT,
                    **remote,
                    "header_url": str(data.get("header_url") or remote.get("header_url") or ""),
                }
                if str(value.get("code", "")).upper() == "UDA" and not value["header_url"]:
                    value["header_url"] = "/static/brand_uda_header.png?v=fd4ae5a0-v172"
            except Exception as exc:
                error = str(exc)
        else:
            error = "PARTY_BRANDING_API_URL is not configured."
        # Both services normally share the master PostgreSQL database. Its
        # singleton is authoritative and also eliminates reliance on a public
        # Render hostname. If this database/table is unavailable, retain the
        # successfully fetched HTTP value above.
        database_url = (
            os.getenv("MASTER_REGISTER_DATABASE_URL", "").strip()
            or os.getenv("DATABASE_URL", "").strip()
        )
        if database_url:
            try:
                with psycopg.connect(
                    database_url,
                    connect_timeout=4,
                    options="-c statement_timeout=4000",
                ) as connection:
                    row = connection.execute(
                        "SELECT party_code FROM app_party_branding WHERE singleton=TRUE"
                    ).fetchone()
                if row:
                    code = str(row[0] or "ODM").upper()
                    if code == "UDA":
                        value = {
                            **DEFAULT,
                            "code": "UDA",
                            "name": "United Democratic Alliance",
                            "abbreviation": "UDA",
                            "slogan": "Usawa Ni Sawa",
                            "membership_prefix": "UDA",
                            "primary": "#11833b",
                            "secondary": "#ffd400",
                            "accent": "#ffffff",
                            "header_url": "/static/brand_uda_header.png?v=fd4ae5a0-v172",
                        }
                    else:
                        value = dict(DEFAULT)
                    error = ""
            except Exception as db_exc:
                if error:
                    error = error + "; database fallback: " + str(db_exc)
        _CACHE.update(at=now, brand=value, error=error)
        return dict(value)


def register_party_branding(app):
    @app.context_processor
    def inject_party_brand():
        return {"party_brand": get_brand()}

    @app.get("/api/party-branding-status")
    def party_branding_status():
        brand = get_brand(force=True)
        return jsonify(
            ok=not bool(_CACHE["error"]),
            source_url=branding_api_url(),
            error=_CACHE["error"],
            brand=brand,
        )

    @app.after_request
    def apply_party_brand(response):
        content_type = str(response.headers.get("Content-Type") or "").lower()
        if response.direct_passthrough or "text/html" not in content_type:
            return response
        try:
            brand = get_brand()
            html = response.get_data(as_text=True)
            header = brand.get("header_url", "")
            if not header and str(brand.get("code", "")).upper() == "UDA":
                header = "/static/brand_uda_header.png?v=fd4ae5a0-v172"
                brand["header_url"] = header
            if header:
                # Only named system-brand images are replaced. Candidate photos are untouched.
                html = re.sub(
                    r'''(?i)(?:https?://[^"']+)?/static/[^"']*(?:odm_orange_voting_banner|odm_screen_header|odm_report_header|odm_pdf_header|voter_verification_logo)[^"']*\.(?:png|jpe?g)(?:\?[^"']*)?''',
                    header,
                    html,
                )
            polling_script = """
<script id="party-brand-live-refresh">
(()=>{
 const apply=b=>{
  if(!b)return;
  document.documentElement.style.setProperty('--party-primary',b.primary||'#ef7d00');
  document.documentElement.style.setProperty('--party-secondary',b.secondary||'#111111');
  document.documentElement.style.setProperty('--party-accent',b.accent||'#fff2df');
  if(b.header_url) document.querySelectorAll('img.candidate-portal-banner').forEach(img=>{
   if(img.src!==b.header_url) img.src=b.header_url;
   img.alt=(b.abbreviation||b.code||'Party')+' 2027 Party Primaries Voting System';
  });
 };
 const refresh=()=>fetch('/api/party-branding-status?_='+Date.now(),{cache:'no-store',credentials:'same-origin'})
  .then(r=>r.ok?r.json():null).then(d=>apply(d&&d.brand)).catch(()=>{});
 setInterval(refresh,10000);
})();
</script>
"""
            addon = (
                '<style id="party-brand-theme">:root{--party-primary:' + brand["primary"]
                + ';--party-secondary:' + brand["secondary"] + ';--party-accent:' + brand["accent"]
                + '}button,.btn,.button{border-color:var(--party-primary)!important}</style>'
                + "<script id=\"party-brand-text\">(()=>{const clean=v=>v.replace(/Orange Democratic Movement/gi,'Party').replace(/\\bODM\\b/gi,'Party');const apply=()=>{document.title=clean(document.title);const w=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);let n;while(n=w.nextNode()){if(['SCRIPT','STYLE','TEXTAREA','OPTION'].includes(n.parentElement?.tagName))continue;n.nodeValue=clean(n.nodeValue)}};if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',apply);else apply();})();</script>"
                + polling_script
            )
            html = html.replace("</head>", addon + "</head>")
            response.set_data(html)
            response.headers["Content-Length"] = str(len(response.get_data()))
        except Exception:
            app.logger.exception("Unable to apply shared party branding")
        return response

    return app
