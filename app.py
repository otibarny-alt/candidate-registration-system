
# V1.32: candidate photos may use a plain background of any colour.
import os, csv, re, uuid, base64, hmac, time, json
from datetime import datetime, timezone
from io import BytesIO, StringIO
import requests
import cv2
import numpy as np
import psycopg
from psycopg.rows import dict_row
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, Response, abort
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text, func, or_
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.security import check_password_hash
from pypdf import PdfReader
from party_branding_client import get_brand, register_party_branding

app=Flask(__name__)
app.secret_key=os.getenv("FLASK_SECRET_KEY","candidate-portal-change-me")
register_party_branding(app)

db_url=(os.getenv("CANDIDATE_DATABASE_URL","").strip()
        or os.getenv("MASTER_REGISTER_DATABASE_URL","").strip()
        or os.getenv("DATABASE_URL","").strip()
        or "sqlite:///candidates.db")
# Render provides a PostgreSQL URL without an explicit driver.
# This application installs Psycopg 3, so tell SQLAlchemy to use it.
if db_url.startswith("postgres://"):
    db_url="postgresql+psycopg://"+db_url[len("postgres://"):]
elif db_url.startswith("postgresql://"):
    db_url="postgresql+psycopg://"+db_url[len("postgresql://"):]
app.config["SQLALCHEMY_DATABASE_URI"]=db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"]=False
app.config["MAX_CONTENT_LENGTH"]=45*1024*1024
db=SQLAlchemy(app)
SYSTEM_RESET_TOKEN=os.getenv("SYSTEM_RESET_TOKEN","").strip()
CANDIDATE_ELIGIBILITY_TOKEN=os.getenv("CANDIDATE_ELIGIBILITY_TOKEN",SYSTEM_RESET_TOKEN).strip()

COUNTY_MAIN=os.getenv("COUNTY_MAIN_FILENAME","county_main.csv")
AUTH_USERNAME=os.getenv("AUTH_USERNAME","admin")
AUTH_PASSWORD_HASH=os.getenv("AUTH_PASSWORD_HASH","")
LEVEL2_ADMIN_USERNAME=os.getenv("LEVEL2_ADMIN_USERNAME","").strip()
LEVEL2_ADMIN_PASSWORD_HASH=os.getenv("LEVEL2_ADMIN_PASSWORD_HASH","").strip()
_CANDIDATE_LOGIN_ATTEMPTS={}

# Central navigation destinations. Every external address may be changed in
# Render without editing the application again.
VOTING_SYSTEM_BASE_URL=os.getenv("VOTING_SYSTEM_BASE_URL","https://voting-simulation-system.onrender.com").strip().rstrip("/")
VERIFICATION_SYSTEM_BASE_URL=os.getenv("VERIFICATION_SYSTEM_BASE_URL","https://odm-member-photo-verifier.onrender.com").strip().rstrip("/")
OFFICIAL_ODM_MEMBERSHIP_URL=os.getenv(
    "OFFICIAL_ODM_MEMBERSHIP_URL","https://www.odmmembership.com/web/"
).strip()

def normalized_results_url(value):
    """Repair the obsolete -results-dashboard host and open the login page."""
    url=str(value or "").strip().rstrip("/")
    url=url.replace("-simulation-results-dashboard.onrender.com","-simulation-results.onrender.com")
    legacy_hosts={
        "https://senatorial-simulation-results.onrender.com":"https://senatorial-results-dashboard.onrender.com",
        "https://women-representative-simulation-results.onrender.com":"https://women-rep-results-dashboard.onrender.com",
        "https://mna-simulation-results.onrender.com":"https://member-of-na-results-dashboard.onrender.com",
        "https://mca-simulation-results.onrender.com":"https://member-of-ca-results-dashboard.onrender.com",
    }
    for old_host,new_host in legacy_hosts.items():
        if url.lower().startswith(old_host):
            url=new_host+url[len(old_host):]
            break
    if url and not url.lower().endswith("/login"):
        url=f"{url}/login"
    return url

RESULT_DASHBOARD_URLS={
    "presidential":normalized_results_url(os.getenv("PRESIDENTIAL_RESULTS_URL","https://presidential-simulation-results.onrender.com/login")),
    "gubernatorial":normalized_results_url(os.getenv("GUBERNATORIAL_RESULTS_URL","https://gubernatorial-simulation-results.onrender.com/login")),
    "senatorial":normalized_results_url(os.getenv("SENATORIAL_RESULTS_URL","https://senatorial-results-dashboard.onrender.com/login")),
    "women_representative":normalized_results_url(os.getenv("WOMEN_REP_RESULTS_URL","https://women-rep-results-dashboard.onrender.com/login")),
    "mna":normalized_results_url(os.getenv("MNA_RESULTS_URL","https://member-of-na-results-dashboard.onrender.com/login")),
    "mca":normalized_results_url(os.getenv("MCA_RESULTS_URL","https://member-of-ca-results-dashboard.onrender.com/login")),
}

def service_url(base,path=""):
    return f"{str(base or '').rstrip('/')}/{str(path or '').lstrip('/')}".rstrip("/")

KOBO_BASE_URL=os.getenv("KOBO_BASE_URL","https://kf.kobotoolbox.org").rstrip("/")
MEMBERSHIP_ASSET_UID=os.getenv("MEMBERSHIP_ASSET_UID","").strip()
KOBO_API_TOKEN=os.getenv("KOBO_API_TOKEN","").strip()
MEMBERSHIP_CSV_FILENAME=os.getenv("MEMBERSHIP_CSV_FILENAME","membership_registration.csv").strip()
MEMBERSHIP_CSV_CACHE_SECONDS=int(os.getenv("MEMBERSHIP_CSV_CACHE_SECONDS","300") or 300)
_MEMBERSHIP_CSV_CACHE={"loaded_at":0.0,"rows":{}}
MASTER_REGISTER_DATABASE_URL=os.getenv("MASTER_REGISTER_DATABASE_URL","").strip()
MASTER_REGISTER_STRICT=os.getenv("MASTER_REGISTER_STRICT","true").strip().lower() in {"1","true","yes","on"}

def set_master_membership_type(national_id,membership_type):
    """Reflect an approved candidate classification in the shared voters register."""
    national_id=re.sub(r"\D","",str(national_id or ""))
    if not MASTER_REGISTER_DATABASE_URL:
        raise RuntimeError("MASTER_REGISTER_DATABASE_URL is not configured.")
    if not national_id:
        raise ValueError("The candidate has no valid National ID.")
    with psycopg.connect(MASTER_REGISTER_DATABASE_URL,connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE master_voters ADD COLUMN IF NOT EXISTS membership_type TEXT NOT NULL DEFAULT 'Ordinary Member'")
            cur.execute("""UPDATE master_voters SET membership_type=%s,updated_at=NOW()
                           WHERE active AND national_id=%s""",(membership_type,national_id))
            if cur.rowcount!=1:
                raise ValueError("The candidate National ID was not found in the active voters register.")
        conn.commit()

def sync_approved_candidate_membership_types():
    ids=[re.sub(r"\D","",str(row.national_id or "")) for row in Candidate.query.filter_by(approval_status="approved").all()]
    ids=sorted({value for value in ids if value})
    if not ids or not MASTER_REGISTER_DATABASE_URL:
        return 0
    with psycopg.connect(MASTER_REGISTER_DATABASE_URL,connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE master_voters ADD COLUMN IF NOT EXISTS membership_type TEXT NOT NULL DEFAULT 'Ordinary Member'")
            cur.execute("""UPDATE master_voters SET membership_type='Life Member',updated_at=NOW()
                           WHERE active AND national_id=ANY(%s)""",(ids,))
            changed=cur.rowcount
        conn.commit()
    return changed

POSITIONS=[
 ("president","President","national"),
 ("governor","Governor","county"),
 ("senator","Senator","county"),
 ("woman_rep","Woman Representative","county"),
 ("mna","MNA","constituency"),
 ("mca","MCA","ward"),
]

PDF_DOCUMENTS=[
 ("id_copy","Copy of ID"),
 ("signed_application_form","Scanned and Signed Application Form"),
 ("eacc_clearance","EACC Clearance"),
 ("income_tax_clearance","Income Tax Clearance"),
 ("good_conduct_certificate","Certificate of Good Conduct"),
 ("life_membership_certificate","Life Membership Certificate Copy"),
 ("signed_code_of_conduct","Signed Code of Conduct"),
 ("payment_receipts","Copy of Payment Receipts"),
 ("summarized_cv","Summarized Curriculum Vitae – 2 page maximum"),
]
GOVERNOR_PDF_DOCUMENT=("academic_certificate","Copy of Highest Academic Certificate")
PLWD_PDF_DOCUMENT=("plwd_identification_card","PLWD Identification Card")
PUBLIC_OFFICER_PDF_DOCUMENT=("acknowledged_resignation_letter","Acknowledged Resignation Letter")
BANKRUPTCY_PDF_DOCUMENT=("bankruptcy_discharge_evidence","Evidence of Discharge")
APPEAL_REVIEW_PDF_DOCUMENT=("appeal_or_review_evidence","Evidence of the Appeal or Review")
CHAPTER_SIX_APPEAL_PDF_DOCUMENT=("chapter_six_appeal_review_evidence","Chapter Six Evidence of the Appeal or Review")

class Candidate(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    candidate_id=db.Column(db.String(80),unique=True,nullable=False,index=True)
    party_code=db.Column(db.String(10),nullable=False,default="ODM",index=True)
    full_name=db.Column(db.String(180),nullable=False)
    national_id=db.Column(db.String(40))
    phone=db.Column(db.String(40))
    date_of_birth=db.Column(db.String(40))
    gender=db.Column(db.String(30))
    email=db.Column(db.String(160))
    membership_no=db.Column(db.String(100))
    living_with_disability=db.Column(db.Boolean,default=False,nullable=False)
    public_officer_recently_resigned=db.Column(db.Boolean,default=False,nullable=False)
    ever_declared_bankrupt=db.Column(db.Boolean,default=False,nullable=False)
    sentence_decision_appealed=db.Column(db.Boolean,default=False,nullable=False)
    chapter_six_conviction_appealed=db.Column(db.Boolean,default=False,nullable=False)
    position=db.Column(db.String(40),nullable=False,index=True)
    county=db.Column(db.String(160),index=True)
    constituency=db.Column(db.String(160),index=True)
    ward=db.Column(db.String(160),index=True)
    bio=db.Column(db.Text)
    photo=db.Column(db.LargeBinary)
    photo_mime=db.Column(db.String(80))
    photo_validated=db.Column(db.Boolean,default=False,nullable=False)
    id_copy=db.Column(db.LargeBinary)
    signed_application_form=db.Column(db.LargeBinary)
    eacc_clearance=db.Column(db.LargeBinary)
    income_tax_clearance=db.Column(db.LargeBinary)
    good_conduct_certificate=db.Column(db.LargeBinary)
    life_membership_certificate=db.Column(db.LargeBinary)
    signed_code_of_conduct=db.Column(db.LargeBinary)
    payment_receipts=db.Column(db.LargeBinary)
    summarized_cv=db.Column(db.LargeBinary)
    academic_certificate=db.Column(db.LargeBinary)
    plwd_identification_card=db.Column(db.LargeBinary)
    acknowledged_resignation_letter=db.Column(db.LargeBinary)
    bankruptcy_discharge_evidence=db.Column(db.LargeBinary)
    appeal_or_review_evidence=db.Column(db.LargeBinary)
    chapter_six_appeal_review_evidence=db.Column(db.LargeBinary)
    status=db.Column(db.String(20),default="active",nullable=False,index=True)
    approval_status=db.Column(db.String(20),default="not_submitted",nullable=False,index=True)
    rejection_reason=db.Column(db.String(80))
    rejection_reasons=db.Column(db.Text)
    application_date=db.Column(db.String(40),index=True)

class PortalState(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    party_code=db.Column(db.String(10),nullable=False,default="ODM",index=True)
    candidate_list_final=db.Column(db.Boolean,default=False,nullable=False)
    locked_at=db.Column(db.String(40))
    locked_by=db.Column(db.String(100))

with app.app_context():
    db.create_all()
    # create_all() does not add columns to an existing Render PostgreSQL table.
    # Apply this small, backwards-compatible migration during deployment.
    candidate_columns={column["name"] for column in inspect(db.engine).get_columns("candidate")}
    if "party_code" not in candidate_columns:
        db.session.execute(text("ALTER TABLE candidate ADD COLUMN party_code VARCHAR(10) NOT NULL DEFAULT 'ODM'"))
    db.session.execute(text("UPDATE candidate SET party_code='ODM' WHERE party_code IS NULL OR party_code=''"))
    db.session.execute(text("CREATE INDEX IF NOT EXISTS idx_candidate_party_code ON candidate (party_code)"))
    db.session.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_candidate_party_national_id ON candidate (party_code,national_id) WHERE national_id IS NOT NULL AND national_id<>''"))
    if "photo_validated" not in candidate_columns:
        db.session.execute(text("ALTER TABLE candidate ADD COLUMN photo_validated BOOLEAN NOT NULL DEFAULT FALSE"))
    if "approval_status" not in candidate_columns:
        db.session.execute(text("ALTER TABLE candidate ADD COLUMN approval_status VARCHAR(20) NOT NULL DEFAULT 'pending'"))
    if "rejection_reason" not in candidate_columns:
        db.session.execute(text("ALTER TABLE candidate ADD COLUMN rejection_reason VARCHAR(80)"))
    if "rejection_reasons" not in candidate_columns:
        db.session.execute(text("ALTER TABLE candidate ADD COLUMN rejection_reasons TEXT"))
    if "application_date" not in candidate_columns:
        db.session.execute(text("ALTER TABLE candidate ADD COLUMN application_date VARCHAR(40)"))
    if "date_of_birth" not in candidate_columns:
        db.session.execute(text("ALTER TABLE candidate ADD COLUMN date_of_birth VARCHAR(40)"))
    if "gender" not in candidate_columns:
        db.session.execute(text("ALTER TABLE candidate ADD COLUMN gender VARCHAR(30)"))
    if "living_with_disability" not in candidate_columns:
        db.session.execute(text("ALTER TABLE candidate ADD COLUMN living_with_disability BOOLEAN NOT NULL DEFAULT FALSE"))
    if "public_officer_recently_resigned" not in candidate_columns:
        db.session.execute(text("ALTER TABLE candidate ADD COLUMN public_officer_recently_resigned BOOLEAN NOT NULL DEFAULT FALSE"))
    if "ever_declared_bankrupt" not in candidate_columns:
        db.session.execute(text("ALTER TABLE candidate ADD COLUMN ever_declared_bankrupt BOOLEAN NOT NULL DEFAULT FALSE"))
    if "sentence_decision_appealed" not in candidate_columns:
        db.session.execute(text("ALTER TABLE candidate ADD COLUMN sentence_decision_appealed BOOLEAN NOT NULL DEFAULT FALSE"))
    if "chapter_six_conviction_appealed" not in candidate_columns:
        db.session.execute(text("ALTER TABLE candidate ADD COLUMN chapter_six_conviction_appealed BOOLEAN NOT NULL DEFAULT FALSE"))
    for document_column,_document_label in (*PDF_DOCUMENTS,GOVERNOR_PDF_DOCUMENT,PLWD_PDF_DOCUMENT,PUBLIC_OFFICER_PDF_DOCUMENT,BANKRUPTCY_PDF_DOCUMENT,APPEAL_REVIEW_PDF_DOCUMENT,CHAPTER_SIX_APPEAL_PDF_DOCUMENT):
        if document_column not in candidate_columns:
            db.session.execute(text(f"ALTER TABLE candidate ADD COLUMN {document_column} BYTEA"))
    portal_state_columns={column["name"] for column in inspect(db.engine).get_columns("portal_state")}
    if "party_code" not in portal_state_columns:
        db.session.execute(text("ALTER TABLE portal_state ADD COLUMN party_code VARCHAR(10) NOT NULL DEFAULT 'ODM'"))
    db.session.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_portal_state_party_code ON portal_state (party_code)"))
    if db.session.get(PortalState,1) is None:
        db.session.add(PortalState(id=1,party_code="ODM",candidate_list_final=False))
    else:
        db.session.execute(text("UPDATE portal_state SET party_code='ODM' WHERE id=1 AND (party_code IS NULL OR party_code='')"))
    # Older incomplete records must be reviewed again and cannot remain accepted.
    db.session.execute(text(
        "UPDATE candidate SET approval_status='pending' "
        "WHERE approval_status='approved' AND (photo IS NULL OR photo_validated=FALSE)"
    ))
    # An application is not submitted for review until passport-photo
    # validation succeeds. Existing unverified pending records become drafts.
    db.session.execute(text(
        "UPDATE candidate SET approval_status='not_submitted' "
        "WHERE approval_status='pending' AND "
        "(photo IS NULL OR photo_validated=FALSE)"
    ))
    db.session.commit()
    try:
        sync_approved_candidate_membership_types()
    except Exception as exc:
        app.logger.warning("Approved candidate membership types could not be synchronized at startup: %s",exc)

def logged_in():
    return bool(session.get("admin"))

def candidate_logged_in():
    return bool(session.get("candidate_national_id"))

def normalized_party_code(value=None):
    code=str(value or "").strip().upper()
    return code if code in {"ODM","UDA"} else "ODM"

def active_candidate_party_code():
    return normalized_party_code((get_brand() or {}).get("code"))

def candidate_session_party_code():
    return normalized_party_code(session.get("candidate_party_code") or active_candidate_party_code())

@app.before_request
def prevent_cross_party_candidate_session():
    """Never show one party's application under the other party's branding."""
    if (candidate_logged_in() and not logged_in() and
        request.path.startswith("/candidate") and
        request.endpoint not in {"candidate_logout","candidate_access","candidate_register"} and
        candidate_session_party_code()!=active_candidate_party_code()):
        session.clear()
        session["candidate_entry_message"]="Party branding changed. Sign in again to open the active party's candidate portal."
        return redirect(url_for("candidate_access"))

@app.errorhandler(SQLAlchemyError)
def candidate_database_error(exc):
    """Keep candidate database outages off the generic white HTTP 500 page."""
    app.logger.exception("Candidate portal database request failed")
    try:db.session.rollback()
    except Exception:pass
    if request.path.startswith("/api/"):
        return jsonify({"ok":False,"error":"The candidate registration database is temporarily unavailable."}),503
    return render_template("database_unavailable.html"),503

@app.post("/api/admin/reset-test-data")
def api_admin_reset_test_data():
    """Internal reset called by the voting-system administrator."""
    supplied=request.headers.get("Authorization","")
    expected="Bearer "+SYSTEM_RESET_TOKEN
    if not SYSTEM_RESET_TOKEN or not hmac.compare_digest(supplied,expected):
        return jsonify({"ok":False,"error":"Unauthorized"}),403
    deleted=Candidate.query.delete(synchronize_session=False)
    state=portal_state()
    state.candidate_list_final=False
    state.locked_at=None
    state.locked_by=None
    db.session.commit()
    return jsonify({"ok":True,"deleted_candidates":deleted})

@app.get("/api/internal/candidate-registration/<national_id>")
def api_internal_candidate_registration(national_id):
    """Tell trusted services whether an ID has any candidate record."""
    supplied=request.headers.get("Authorization","")
    expected="Bearer "+CANDIDATE_ELIGIBILITY_TOKEN
    if not CANDIDATE_ELIGIBILITY_TOKEN or not hmac.compare_digest(supplied,expected):
        return jsonify({"ok":False,"error":"Unauthorized"}),403
    normalized=re.sub(r"\D","",str(national_id or ""))
    if not normalized:
        return jsonify({"ok":False,"error":"A valid National ID is required."}),400
    # Membership changes remain locked if the ID is a candidate for either
    # party. This endpoint intentionally does not apply the active-party filter.
    candidate=Candidate.query.filter_by(national_id=normalized).first()
    return jsonify({"ok":True,"registered":bool(candidate)})

def require_login():
    if not logged_in():
        return redirect(url_for("login"))
    return None

def portal_state(party_code=None):
    code=normalized_party_code(party_code or active_candidate_party_code())
    state=PortalState.query.filter_by(party_code=code).first()
    if state is None:
        state=PortalState(party_code=code,candidate_list_final=False)
        db.session.add(state)
        db.session.commit()
    return state

def candidate_list_is_final():
    code=candidate_session_party_code() if candidate_logged_in() and not logged_in() else active_candidate_party_code()
    return bool(portal_state(code).candidate_list_final)

def admin_csrf_token():
    token=session.get("admin_csrf_token")
    if not token:
        token=uuid.uuid4().hex
        session["admin_csrf_token"]=token
    return token

def valid_admin_csrf():
    supplied=request.form.get("csrf_token","")
    expected=session.get("admin_csrf_token","")
    return bool(supplied and expected and hmac.compare_digest(supplied,expected))

def candidate_session_national_id():
    return str(session.get("candidate_national_id") or "").strip()

def candidate_can_access(c):
    same_party=normalized_party_code(c.party_code)==(active_candidate_party_code() if logged_in() else candidate_session_party_code())
    return same_party and (logged_in() or (
        candidate_logged_in() and
        hmac.compare_digest(str(c.national_id or "").strip(),candidate_session_national_id())
    ))

def norm(v):
    return re.sub(r"[^a-z0-9]+","_",str(v or "").strip().lower()).strip("_")

def phone_key(value):
    """Compare Kenyan phone formats by their stable final nine digits."""
    digits=re.sub(r"\D+","",str(value or ""))
    return digits[-9:] if len(digits)>=9 else digits

def candidate_login_rate_limited(client_key):
    now=time.time()
    recent=[stamp for stamp in _CANDIDATE_LOGIN_ATTEMPTS.get(client_key,[]) if now-stamp<900]
    _CANDIDATE_LOGIN_ATTEMPTS[client_key]=recent
    return len(recent)>=8

def record_candidate_login_failure(client_key):
    _CANDIDATE_LOGIN_ATTEMPTS.setdefault(client_key,[]).append(time.time())

def validated_image_upload(upload, field_label, max_bytes=5*1024*1024):
    """Read and validate a JPG, PNG or WebP upload by its actual signature."""
    if not upload or not str(upload.filename or "").strip():
        return None, None
    data=upload.read(max_bytes+1)
    if not data:
        raise ValueError(f"{field_label} is empty.")
    if len(data)>max_bytes:
        raise ValueError(f"{field_label} must not exceed 5 MB.")
    if data.startswith(b"\xff\xd8\xff"):
        mime="image/jpeg"
    elif data.startswith(b"\x89PNG\r\n\x1a\n"):
        mime="image/png"
    elif len(data)>=12 and data[:4]==b"RIFF" and data[8:12]==b"WEBP":
        mime="image/webp"
    else:
        raise ValueError(f"{field_label} must be a valid JPG, PNG or WebP image.")
    return data, mime

def validated_pdf_upload(upload,field_label,max_bytes=5*1024*1024,max_pages=None):
    """Accept only a real PDF payload, not a renamed image or executable."""
    if not upload or not str(upload.filename or "").strip():
        return None
    data=upload.read(max_bytes+1)
    if not data:
        raise ValueError(f"{field_label} is empty.")
    if len(data)>max_bytes:
        raise ValueError(f"{field_label} must not exceed 5 MB.")
    if not data.startswith(b"%PDF-"):
        raise ValueError(f"{field_label} must be a valid PDF file.")
    if b"%%EOF" not in data[-4096:]:
        raise ValueError(f"{field_label} is incomplete or damaged. Upload a complete PDF.")
    if max_pages is not None:
        try:
            page_count=len(PdfReader(BytesIO(data)).pages)
        except Exception as exc:
            raise ValueError(f"{field_label} could not be read. Upload a valid, unencrypted PDF.") from exc
        if page_count>max_pages:
            raise ValueError(f"{field_label} must not exceed {max_pages} pages. The uploaded PDF has {page_count} pages.")
    return data

def candidate_required_documents(c):
    documents=list(PDF_DOCUMENTS)
    if c and c.position=="governor":
        documents.append(GOVERNOR_PDF_DOCUMENT)
    if c and c.living_with_disability:
        documents.append(PLWD_PDF_DOCUMENT)
    if c and c.public_officer_recently_resigned:
        documents.append(PUBLIC_OFFICER_PDF_DOCUMENT)
    if c and c.ever_declared_bankrupt:
        documents.append(BANKRUPTCY_PDF_DOCUMENT)
    if c and c.sentence_decision_appealed:
        documents.append(APPEAL_REVIEW_PDF_DOCUMENT)
    if c and c.chapter_six_conviction_appealed:
        documents.append(CHAPTER_SIX_APPEAL_PDF_DOCUMENT)
    return documents

def candidate_missing_documents(c):
    return [label for field,label in candidate_required_documents(c) if not getattr(c,field,None)]

def candidate_application_progress(c):
    documents=candidate_required_documents(c) if c else list(PDF_DOCUMENTS)
    total=1+len(documents)
    completed=0
    if c and c.photo and c.photo_validated:
        completed+=1
    if c:
        completed+=sum(1 for field,_label in documents if getattr(c,field,None))
    percent=round((completed*100)/total) if total else 100
    return {"completed":completed,"total":total,"percent":percent}

DECLARATION_FIELDS=(
    ("living_with_disability","Are you a Person Living with Disability?"),
    ("public_officer_recently_resigned","Are you a Public Officer who has recently Resigned?"),
    ("ever_declared_bankrupt","Have you ever been declared bankrupt?"),
    ("sentence_decision_appealed","Are You subject of a Sentence and have appealed the Decision?"),
    ("chapter_six_conviction_appealed","Have you ever been convicted of contravening Chapter Six of the Constitution and have appealed the Decision?"),
)

def update_candidate_editable_fields(c, form):
    email=form.get("email",c.email or "").strip()[:160]
    if email and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+",email):
        raise ValueError("Enter a valid email address.")
    c.email=email
    c.bio=form.get("bio",c.bio or "").strip()
    for field,label in DECLARATION_FIELDS:
        answer=form.get(field,"").strip().lower()
        if answer not in {"yes","no"}:
            raise ValueError(f"Select YES or NO for {label}")
        setattr(c,field,answer=="yes")

def candidate_document_catalog(c):
    return [
        ("passport_photo","Passport Photo",bool(c and c.photo and c.photo_validated)),
        *[(field,label,bool(c and getattr(c,field,None))) for field,label in candidate_required_documents(c)]
    ]

def candidate_rejection_keys(c):
    try:
        values=json.loads(c.rejection_reasons or "[]")
        if isinstance(values,list):
            return [str(value) for value in values]
    except (TypeError,ValueError):
        pass
    if c.rejection_reason=="improper_candidate_picture":
        return ["passport_photo"]
    return []

def candidate_rejection_labels(c):
    selected=set(candidate_rejection_keys(c))
    return [label for key,label,_present in candidate_document_catalog(c) if key in selected]

def save_candidate_pdf_uploads(c):
    changed=set()
    for field,label in (*PDF_DOCUMENTS,GOVERNOR_PDF_DOCUMENT,PLWD_PDF_DOCUMENT,PUBLIC_OFFICER_PDF_DOCUMENT,BANKRUPTCY_PDF_DOCUMENT,APPEAL_REVIEW_PDF_DOCUMENT,CHAPTER_SIX_APPEAL_PDF_DOCUMENT):
        upload=request.files.get(field)
        if upload and str(upload.filename or "").strip():
            max_pages=2 if field=="summarized_cv" else None
            setattr(c,field,validated_pdf_upload(upload,label,max_pages=max_pages))
            changed.add(field)
    return changed

_FACE_CASCADES=[cv2.CascadeClassifier(os.path.join(cv2.data.haarcascades,name)) for name in (
    "haarcascade_frontalface_default.xml",
    "haarcascade_frontalface_alt2.xml",
    "haarcascade_frontalface_alt.xml",
)]

def validated_candidate_photo(cropped_photo):
    """Decode a crop and require a readable candidate portrait."""
    try:
        header,encoded=str(cropped_photo or "").split(",",1)
        if header.lower() not in {"data:image/jpeg;base64","data:image/jpg;base64"}:
            raise ValueError("Passport Photo must be cropped using the photo tool.")
        if len(encoded)>8*1024*1024:
            raise ValueError("Passport Photo is too large. Select and crop a smaller image.")
        data=base64.b64decode(encoded,validate=True)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Passport Photo could not be decoded. Select and crop it again.") from exc

    image=cv2.imdecode(np.frombuffer(data,dtype=np.uint8),cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Passport Photo is not a readable image.")
    height,width=image.shape[:2]
    if width<300 or height<375:
        raise ValueError("Passport Photo is too small. Use a clearer, higher-resolution photograph.")
    if all(cascade.empty() for cascade in _FACE_CASCADES):
        raise RuntimeError("Passport photo validation is temporarily unavailable. Please contact the administrator.")

    gray=cv2.equalizeHist(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY))
    min_face=max(44,int(min(width,height)*0.12))
    raw_faces=[]
    # Try increasingly tolerant frontal-face models. Stop at the first model
    # that detects a face so the same face is not counted once per model.
    for cascade in _FACE_CASCADES:
        if cascade.empty():continue
        detected=cascade.detectMultiScale(
            gray,scaleFactor=1.06,minNeighbors=3,minSize=(min_face,min_face)
        )
        if len(detected):
            raw_faces=detected;break
    # Haar cascades can return two strongly overlapping boxes for the same
    # person, especially after a small source portrait is enlarged by the
    # cropper. Merge those duplicates but retain genuinely separate faces.
    faces=[]
    for candidate in sorted(raw_faces,key=lambda box:int(box[2])*int(box[3]),reverse=True):
        cx,cy,cw,ch=[int(value) for value in candidate]
        duplicate=False
        for kept in faces:
            kx,ky,kw,kh=kept
            ix=max(0,min(cx+cw,kx+kw)-max(cx,kx))
            iy=max(0,min(cy+ch,ky+kh)-max(cy,ky))
            intersection=ix*iy
            union=cw*ch+kw*kh-intersection
            if union and intersection/union>0.35:
                duplicate=True;break
        if not duplicate:faces.append((cx,cy,cw,ch))
    if len(faces)==0:
        raise ValueError("No clear front-facing face was detected. Use a passport-style photograph.")
    # The largest detection is the candidate. Other Haar detections are not a
    # reliable multiple-person signal: patterned clothing, textured hair,
    # jewellery and shadows regularly produce false face boxes. Candidate
    # suitability beyond the primary detected face remains an admin decision.
    faces.sort(key=lambda box:int(box[2])*int(box[3]),reverse=True)
    primary=faces[0]
    x,y,face_width,face_height=[int(value) for value in primary]
    face_ratio=(face_width*face_height)/float(width*height)
    if face_ratio<0.055:
        raise ValueError("The face is too small. Crop closer so the face is clearly visible.")
    if face_ratio>0.62:
        raise ValueError("The face is cropped too closely. Include the full head and some background.")
    face_center_x=x+face_width/2
    face_center_y=y+face_height/2
    if abs(face_center_x-width/2)>width*0.22 or not height*0.22<=face_center_y<=height*0.58:
        raise ValueError("Center the applicant's face in the passport-photo frame and crop again.")

    face_gray=gray[max(0,y):min(height,y+face_height),max(0,x):min(width,x+face_width)]
    if face_gray.size==0 or cv2.Laplacian(face_gray,cv2.CV_64F).var()<12:
        raise ValueError("The face appears blurred. Upload a sharper photograph with good lighting.")

    return data,"image/jpeg"

def hierarchy_rows():
    try:
        with open(COUNTY_MAIN,encoding="utf-8-sig",errors="replace",newline="") as f:
            return list(csv.DictReader(f))
    except Exception:
        return []

def hierarchy_payload():
    rows=hierarchy_rows()
    return {
      "counties":[{"name":r["name"],"label":r.get("label") or r["name"]} for r in rows if r.get("list_name")=="county"],
      "constituencies":[{"name":r["name"],"label":r.get("label") or r["name"],"county_key":r.get("county_key","")} for r in rows if r.get("list_name")=="constituency"],
      "wards":[{"name":r["name"],"label":r.get("label") or r["name"],"constituency_key":r.get("constituency_key","")} for r in rows if r.get("list_name")=="ward"],
    }

def voter_geography_from_membership(row):
    """Resolve a member's authoritative electoral area, preferring station code."""
    county=first_value(row,"electorals_units/county","electorals_units/selected_county","electorals_units/county_name","county")
    constituency=first_value(row,"electorals_units/constituency","electorals_units/selected_constituency","electorals_units/selected_constituency1","constituency")
    ward=first_value(row,"electorals_units/ward","electorals_units/selected_ward","electorals_units/selected_ward1","ward")
    station=first_value(row,"electorals_units/selected_poll_station1","electorals_units/poll_station_label","poll_station")
    station_code=first_value(row,"electorals_units/selected_poll_station1_code","electorals_units/poll_station_code","poll_station_code")

    rows=hierarchy_rows()
    counties={norm(r.get("name")):r for r in rows if r.get("list_name")=="county"}
    constituencies={norm(r.get("name")):r for r in rows if r.get("list_name")=="constituency"}
    wards={norm(r.get("name")):r for r in rows if r.get("list_name")=="ward"}
    stations=[r for r in rows if r.get("list_name")=="poll_station"]
    matches=[]
    code_digits=re.sub(r"\D+","",station_code)
    if code_digits:
        matches=[r for r in stations if re.sub(r"\D+","",str(r.get("poll_station_code") or ""))==code_digits]
    if not matches and station:
        matches=[r for r in stations if norm(r.get("name"))==norm(station) or norm(r.get("label"))==norm(station)]
    # Direct Kobo geography safely disambiguates a repeated polling-station name.
    if len(matches)>1 and ward:
        matches=[r for r in matches if norm(r.get("ward_key"))==norm(ward)]
    if len(matches)==1:
        ward_row=wards.get(norm(matches[0].get("ward_key")),{})
        constituency_row=constituencies.get(norm(ward_row.get("constituency_key")),{})
        county_row=counties.get(norm(constituency_row.get("county_key")),{})
        ward=ward_row.get("name") or ward
        constituency=constituency_row.get("name") or constituency
        county=county_row.get("name") or county
    return {
        "county":county,"constituency":constituency,"ward":ward,
        "polling_station":station,"polling_station_code":station_code,
        "geography_verified":bool(county and constituency and ward)
    }

def application_area_error(position,county,constituency,ward,member):
    if position=="president":
        return ""
    voter_county=member.get("county","")
    voter_constituency=member.get("constituency","")
    voter_ward=member.get("ward","")
    if not member.get("geography_verified"):
        return "Your voter county, constituency and ward could not be verified from Membership Registration. Update the voter registration record before applying for a non-presidential position."
    if norm(county)!=norm(voter_county):
        return f"This application is not allowed. You are registered as a voter in {voter_county}, not {county or 'the selected county'}."
    if position=="mna" and norm(constituency)!=norm(voter_constituency):
        return f"This MNA application is not allowed. You are registered as a voter in {voter_constituency} Constituency."
    if position=="mca" and (norm(constituency)!=norm(voter_constituency) or norm(ward)!=norm(voter_ward)):
        return f"This MCA application is not allowed. You are registered as a voter in {voter_ward} Ward, {voter_constituency} Constituency."
    return ""

def position_scope(position):
    return dict((k,scope) for k,_,scope in POSITIONS).get(position,"national")


def kobo_headers():
    return {"Authorization": f"Token {KOBO_API_TOKEN}"}

def first_value(row, *keys):
    for key in keys:
        value=row.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""

def _lookup_membership_kobo(national_id):
    """Return the most recent live Kobo membership record for a National ID."""
    if not MEMBERSHIP_ASSET_UID or not KOBO_API_TOKEN:
        raise RuntimeError("Kobo Membership Registration connection is not configured in Render.")

    url=f"{KOBO_BASE_URL}/api/v2/assets/{MEMBERSHIP_ASSET_UID}/data/"
    query={"basics/national_id_no": str(national_id).strip()}
    r=requests.get(
        url,
        headers=kobo_headers(),
        params={"query": __import__("json").dumps(query)},
        timeout=25
    )
    r.raise_for_status()
    payload=r.json()
    rows=payload.get("results", payload if isinstance(payload, list) else [])
    if not rows:
        return None

    # Prefer the newest submission when duplicates exist.
    rows=sorted(rows, key=lambda x: str(x.get("_submission_time","")), reverse=True)
    row=rows[0]

    first=first_value(
        row,
        "members_particulars/first_name",
        "basics/first_name",
        "first_name"
    )
    other=first_value(
        row,
        "members_particulars/other_names",
        "members_particulars/other_name",
        "basics/other_names",
        "other_names"
    )
    surname=first_value(
        row,
        "members_particulars/surname",
        "members_particulars/last_name",
        "basics/surname",
        "surname"
    )
    full_name=" ".join(x for x in [first, other, surname] if x).strip()
    if not full_name:
        full_name=first_value(
            row,
            "members_particulars/full_name",
            "basics/full_name",
            "full_name",
            "name"
        )

    phone=first_value(
        row,
        "basics/phone_no",
        "basics/phone_number",
        "members_particulars/phone_no",
        "members_particulars/phone_number",
        "phone_no",
        "phone_number",
        "phone"
    )
    email=first_value(
        row,
        "basics/email",
        "basics/email_address",
        "members_particulars/email",
        "members_particulars/email_address",
        "email",
        "email_address"
    )
    membership_no=first_value(
        row,
        "members_particulars/odm_membership_no",
        "members_particulars/membership_no",
        "odm_membership_no",
        "membership_no"
    )
    date_of_birth=first_value(
        row,
        "basics/dob","basics/date_of_birth",
        "members_particulars/dob","members_particulars/date_of_birth",
        "dob","date_of_birth"
    )
    gender=first_value(
        row,
        "basics/gender","basics/sex",
        "members_particulars/gender","members_particulars/sex",
        "gender","sex"
    )

    geography=voter_geography_from_membership(row)
    return {
        "national_id": first_value(row, "basics/national_id_no", "national_id_no") or str(national_id).strip(),
        "full_name": full_name,
        "phone": phone,
        "date_of_birth": date_of_birth,
        "gender": gender,
        "email": email,
        "membership_no": membership_no,
        "submission_id": row.get("_id"),
        **geography
    }

def _kobo_media_files():
    results=[]
    url=f"{KOBO_BASE_URL}/api/v2/assets/{MEMBERSHIP_ASSET_UID}/files/"
    while url:
        response=requests.get(url,headers=kobo_headers(),timeout=30)
        response.raise_for_status()
        payload=response.json()
        results.extend(payload.get("results",[]))
        url=payload.get("next")
    return results

def _load_membership_csv():
    now=time.time()
    if _MEMBERSHIP_CSV_CACHE["rows"] and now-_MEMBERSHIP_CSV_CACHE["loaded_at"]<MEMBERSHIP_CSV_CACHE_SECONDS:
        return _MEMBERSHIP_CSV_CACHE["rows"]
    content=None
    media_error=None
    if MEMBERSHIP_ASSET_UID and KOBO_API_TOKEN:
        try:
            for item in _kobo_media_files():
                filename=str((item.get("metadata") or {}).get("filename") or "").strip()
                if filename.lower()==MEMBERSHIP_CSV_FILENAME.lower() and item.get("content"):
                    response=requests.get(item["content"],headers=kobo_headers(),timeout=60)
                    response.raise_for_status()
                    content=response.content
                    break
        except Exception as exc:
            media_error=exc
    if content is None:
        local_path=os.path.join(app.root_path,MEMBERSHIP_CSV_FILENAME)
        if os.path.isfile(local_path):
            with open(local_path,"rb") as source:
                content=source.read()
        elif media_error:
            raise RuntimeError(f"Unable to load {MEMBERSHIP_CSV_FILENAME} from Kobo media: {media_error}")
        else:
            return {}
    rows={}
    for raw in csv.DictReader(StringIO(content.decode("utf-8-sig",errors="replace"))):
        row={str(k or "").strip():("" if v is None else str(v).strip()) for k,v in raw.items()}
        national_id=re.sub(r"\D","",row.get("national_id_no",""))
        if national_id:
            rows[national_id]=row
    _MEMBERSHIP_CSV_CACHE.update(loaded_at=now,rows=rows)
    return rows

def _membership_from_csv(national_id):
    row=_load_membership_csv().get(re.sub(r"\D","",str(national_id or "")))
    if not row:
        return None
    geography=voter_geography_from_membership(row)
    return {
        "national_id":row.get("national_id_no",""),
        "full_name":" ".join(filter(None,[row.get("first_name"),row.get("middle_name"),row.get("surname")])).strip(),
        "phone":row.get("phone_no",""),
        "date_of_birth":row.get("dob","") or row.get("date_of_birth",""),
        "gender":row.get("gender",""),
        "email":row.get("email",""),
        "membership_no":row.get("odm_membership_no",""),
        "submission_id":"membership-csv:"+row.get("national_id_no",""),
        "membership_source":MEMBERSHIP_CSV_FILENAME,
        **geography,
    }

def _membership_from_master_register(national_id):
    """Read the authoritative voter record imported into PostgreSQL."""
    if not MASTER_REGISTER_DATABASE_URL:
        raise RuntimeError("MASTER_REGISTER_DATABASE_URL is not configured in Render.")
    normalized=re.sub(r"\D","",str(national_id or ""))
    if not normalized:
        return None
    with psycopg.connect(
        MASTER_REGISTER_DATABASE_URL,
        row_factory=dict_row,
        connect_timeout=3,
        options="-c statement_timeout=5000",
    ) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT national_id,party_membership_number,first_name,middle_name,
                                  surname,full_name,phone,date_of_birth,gender,county,constituency,ward,
                                  polling_station,polling_station_code
                           FROM master_voters
                           WHERE active AND national_id=%s LIMIT 1""",(normalized,))
            row=cur.fetchone()
    if not row:
        return None
    full_name=str(row.get("full_name") or "").strip() or " ".join(
        str(row.get(key) or "").strip()
        for key in ("first_name","middle_name","surname")
        if str(row.get(key) or "").strip()
    )
    county=str(row.get("county") or "").strip()
    constituency=str(row.get("constituency") or "").strip()
    ward=str(row.get("ward") or "").strip()
    return {
        "national_id":str(row.get("national_id") or normalized).strip(),
        "full_name":full_name,
        "phone":str(row.get("phone") or "").strip(),
        "date_of_birth":str(row.get("date_of_birth") or "").strip(),
        "gender":str(row.get("gender") or "").strip(),
        "email":"",
        "membership_no":str(row.get("party_membership_number") or "").strip(),
        "county":county,
        "constituency":constituency,
        "ward":ward,
        "polling_station":str(row.get("polling_station") or "").strip(),
        "polling_station_code":str(row.get("polling_station_code") or "").strip(),
        "geography_verified":bool(county and constituency and ward),
        "submission_id":"master-voters:"+normalized,
        "membership_source":"postgresql_master_voters",
    }

def lookup_membership(national_id):
    """Use master_voters first, then retain eligible pre-migration Kobo members."""
    if MASTER_REGISTER_DATABASE_URL:
        try:
            member=_membership_from_master_register(national_id)
        except Exception as exc:
            if MASTER_REGISTER_STRICT:
                raise RuntimeError("Unable to contact the new master voters register. Please try again.") from exc
            member=None
        if member:
            return member
    elif MASTER_REGISTER_STRICT:
        raise RuntimeError("MASTER_REGISTER_DATABASE_URL is not configured in Render.")
    live_error=None
    try:
        member=_lookup_membership_kobo(national_id)
        if member:
            member["membership_source"]="kobo_submission"
            return member
    except Exception as exc:
        live_error=exc
    member=_membership_from_csv(national_id)
    if member:
        return member
    if live_error:
        raise live_error
    return None


def existing_candidate_for_national_id(national_id, exclude_candidate_id=None, party_code=None):
    code=normalized_party_code(party_code or (candidate_session_party_code() if candidate_logged_in() else active_candidate_party_code()))
    q=Candidate.query.filter_by(national_id=str(national_id).strip(),party_code=code)
    if exclude_candidate_id is not None:
        q=q.filter(Candidate.id != exclude_candidate_id)
    return q.first()

def candidate_dict(c):
    return {
      "id":c.id,
      "candidate_id":c.candidate_id,
      "party_code":normalized_party_code(c.party_code),
      "full_name":c.full_name,
      "national_id":c.national_id or "",
      "phone":c.phone or "",
      "date_of_birth":c.date_of_birth or "",
      "gender":c.gender or "",
      "email":c.email or "",
      "membership_no":c.membership_no or "",
      "living_with_disability":bool(c.living_with_disability),
      "public_officer_recently_resigned":bool(c.public_officer_recently_resigned),
      "ever_declared_bankrupt":bool(c.ever_declared_bankrupt),
      "sentence_decision_appealed":bool(c.sentence_decision_appealed),
      "chapter_six_conviction_appealed":bool(c.chapter_six_conviction_appealed),
      "position":c.position,
      "county":c.county or "",
      "constituency":c.constituency or "",
      "ward":c.ward or "",
      "bio":c.bio or "",
      "status":c.status,
      "approval_status":c.approval_status,
      "photo_url":url_for("candidate_photo",candidate_id=c.id,_external=True) if c.photo else None
    }

def render_candidate_form_page(candidate=None, **context):
    self_service=not logged_in()
    raw_member=session.get("candidate_member",{})
    verified_member=dict(raw_member) if isinstance(raw_member,dict) else {}
    required_member_fields=("national_id","full_name","phone","date_of_birth","gender","email","membership_no","county","constituency","ward","polling_station","polling_station_code")
    for field in required_member_fields:
        verified_member[field]=str(verified_member.get(field,"") or "")
    verified_member["geography_verified"]=bool(verified_member.get("geography_verified"))

    # Candidates who remained logged in across the V1.13 deployment have an
    # older session without voter-area fields. Refresh it transparently instead
    # of allowing an Undefined value to trigger an HTTP 500 in the template.
    if self_service and candidate_logged_in() and not verified_member["geography_verified"]:
        try:
            refreshed=lookup_membership(candidate_session_national_id())
            if refreshed and (
                not verified_member["phone"] or
                hmac.compare_digest(phone_key(refreshed.get("phone","")),phone_key(verified_member["phone"]))
            ):
                verified_member={
                    field:(bool(refreshed.get(field)) if field=="geography_verified" else str(refreshed.get(field,"") or ""))
                    for field in (*required_member_fields,"geography_verified")
                }
                session["candidate_member"]=verified_member
        except Exception:
            # Safe empty defaults keep the page usable. The save route performs
            # a fresh authoritative lookup and blocks unverifiable geography.
            pass
    return render_template(
        "candidate_form.html",
        candidate=candidate,
        positions=POSITIONS,
        self_service=self_service,
        verified_member=verified_member,
        list_locked=candidate_list_is_final(),
        pdf_documents=PDF_DOCUMENTS,
        governor_pdf_document=GOVERNOR_PDF_DOCUMENT,
        plwd_pdf_document=PLWD_PDF_DOCUMENT,
        public_officer_pdf_document=PUBLIC_OFFICER_PDF_DOCUMENT,
        bankruptcy_pdf_document=BANKRUPTCY_PDF_DOCUMENT,
        appeal_review_pdf_document=APPEAL_REVIEW_PDF_DOCUMENT,
        chapter_six_appeal_pdf_document=CHAPTER_SIX_APPEAL_PDF_DOCUMENT,
        rejection_document_keys=candidate_rejection_keys(candidate) if candidate else [],
        rejection_document_labels=candidate_rejection_labels(candidate) if candidate else [],
        application_progress=candidate_application_progress(candidate),
        **context
    )

@app.get("/main-dashboard")
@app.get("/navigation")
def main_navigation_dashboard():
    party_code=active_candidate_party_code()
    candidate_entry="uda_candidate_register" if party_code=="UDA" else "odm_candidate_register"
    services=[
        {"group":"Registration & Lookup","title":"Membership Registration","description":"Register a new member or open an existing membership record.","url":service_url(VOTING_SYSTEM_BASE_URL,"membership"),"icon":"MEM"},
        {"group":"Registration & Lookup","title":"Official ODM Membership Registration","description":"Open the official ODM membership website to register through ODM Membership.","url":OFFICIAL_ODM_MEMBERSHIP_URL,"icon":"ODM","external":True},
        {"group":"Registration & Lookup","title":party_code+" Candidate Registration","description":"Start a candidate application or access an existing "+party_code+" application.","url":url_for(candidate_entry),"icon":"CAN"},
        {"group":"Registration & Lookup","title":"Public Candidate Applicants","description":"View applicant names and photographs by party, area and position.","url":url_for("public_candidate_applicants"),"icon":"LIST"},
        {"group":"Polling Terminals","title":"ID to Serial Number Lookup","description":"Sign in to the polling-station lookup terminal and retrieve a voter serial number.","url":service_url(VOTING_SYSTEM_BASE_URL,"id-serial-lookup"),"icon":"ID"},
        {"group":"Registration & Lookup","title":"Membership / Polling Centre Lookup","description":"Use a National ID to find the voter's registered name and polling centre.","url":service_url(VOTING_SYSTEM_BASE_URL,"voter-polling-center-lookup"),"icon":"LOC"},
        {"group":"Polling Terminals","title":"Entrance Verification Terminal","description":"Log in to verify voters before they proceed to vote.","url":service_url(VERIFICATION_SYSTEM_BASE_URL,"login"),"icon":"VER"},
        {"group":"Polling Terminals","title":"Voting Terminal","description":"Log in to the station voting terminal after entrance verification is active.","url":service_url(VOTING_SYSTEM_BASE_URL,"terminal-login"),"icon":"VOTE"},
        {"group":"Results Dashboards","title":"Gubernatorial Results","description":"Open the Gubernatorial nomination results dashboard.","url":RESULT_DASHBOARD_URLS["gubernatorial"],"icon":"G"},
        {"group":"Results Dashboards","title":"Senatorial Results","description":"Open the Senatorial nomination results dashboard.","url":RESULT_DASHBOARD_URLS["senatorial"],"icon":"S"},
        {"group":"Results Dashboards","title":"Women Representative Results","description":"Open the Women Representative nomination results dashboard.","url":RESULT_DASHBOARD_URLS["women_representative"],"icon":"WR"},
        {"group":"Results Dashboards","title":"MNA Results","description":"Open the Member of National Assembly results dashboard.","url":RESULT_DASHBOARD_URLS["mna"],"icon":"MNA"},
        {"group":"Results Dashboards","title":"MCA Results","description":"Open the Member of County Assembly results dashboard.","url":RESULT_DASHBOARD_URLS["mca"],"icon":"MCA"},
    ]
    groups=[]
    for name in ("Registration & Lookup","Polling Terminals","Results Dashboards"):
        groups.append((name,[item for item in services if item["group"]==name]))
    return render_template("main_dashboard.html",groups=groups)

@app.get("/candidate-applicants")
@app.get("/public/candidate-applicants")
def public_candidate_applicants():
    """Public, read-only ballot-style gallery of submitted applications."""
    selected={
        "party_code":normalized_party_code(request.args.get("party_code") or active_candidate_party_code()),
        "county":request.args.get("county","").strip()[:160],
        "constituency":request.args.get("constituency","").strip()[:160],
        "ward":request.args.get("ward","").strip()[:160],
        "position":request.args.get("position","").strip()[:40],
    }
    county_selected=bool(selected["county"])
    candidates=[]
    if county_selected:
        query=Candidate.query.filter(
            Candidate.party_code==selected["party_code"],
            Candidate.status=="active",
            Candidate.approval_status.in_(("pending","approved","rejected")),
            Candidate.photo.isnot(None),
            Candidate.photo_validated.is_(True),
        )
        query=query.filter(or_(
            Candidate.position=="president",
            func.lower(Candidate.county)==selected["county"].lower(),
        ))
        if selected["constituency"]:
            query=query.filter(or_(
                Candidate.position.in_(("president","governor","senator","woman_rep")),
                func.lower(Candidate.constituency)==selected["constituency"].lower(),
            ))
        if selected["ward"]:
            query=query.filter(or_(
                Candidate.position.in_(("president","governor","senator","woman_rep","mna")),
                func.lower(Candidate.ward)==selected["ward"].lower(),
            ))
        if selected["position"]:
            query=query.filter(Candidate.position==selected["position"])
        candidates=query.order_by(Candidate.position,Candidate.full_name).all()
    return render_template(
        "public_candidate_applicants.html",
        candidates=candidates,
        positions=POSITIONS,
        position_labels={key:label for key,label,_scope in POSITIONS},
        hierarchy=hierarchy_payload(),
        selected_filters=selected,
        county_selected=county_selected,
    )

@app.get("/login")
def login():
    return render_template("login.html")

@app.post("/login")
def login_post():
    u=request.form.get("username","")
    p=request.form.get("password","")
    ok=(u==AUTH_USERNAME and AUTH_PASSWORD_HASH and check_password_hash(AUTH_PASSWORD_HASH,p))
    if not ok:
        return render_template("login.html",error="Invalid username or password.")
    session.clear()
    session["admin"]=True
    return redirect(url_for("dashboard"))

@app.route("/candidate-access",methods=["GET","POST"])
def candidate_access():
    if request.method=="GET":
        return render_template("candidate_access.html",message=session.pop("candidate_entry_message",None))
    client_key=request.headers.get("X-Forwarded-For",request.remote_addr or "").split(",")[0].strip()
    if candidate_login_rate_limited(client_key):
        return render_template("candidate_access.html",error="Too many unsuccessful attempts. Please wait 15 minutes before trying again."),429
    national_id=request.form.get("national_id","").strip()
    phone=request.form.get("phone","").strip()
    if not national_id.isdigit() or not phone_key(phone):
        record_candidate_login_failure(client_key)
        return render_template("candidate_access.html",error="Enter a valid National ID and registered phone number."),400
    try:
        member=lookup_membership(national_id)
    except requests.RequestException:
        return render_template("candidate_access.html",error="Unable to contact the membership lookup sources. Please try again."),502
    except RuntimeError as exc:
        return render_template("candidate_access.html",error=str(exc)),500
    registered_phone=phone_key((member or {}).get("phone",""))
    if not member or not registered_phone or not hmac.compare_digest(registered_phone,phone_key(phone)):
        record_candidate_login_failure(client_key)
        return render_template("candidate_access.html",error="The National ID and phone number do not match the membership record."),403
    party_code=active_candidate_party_code()
    if not existing_candidate_for_national_id(national_id,party_code=party_code):
        return render_template("candidate_access.html",error="No candidate application was found for this National ID. Use New Candidate Registration to submit a new application."),404
    _CANDIDATE_LOGIN_ATTEMPTS.pop(client_key,None)
    session.clear()
    session["candidate_national_id"]=national_id
    session["candidate_party_code"]=party_code
    session["candidate_member"]={k:(member.get(k,False) if k=="geography_verified" else str(member.get(k,"") or "")) for k in ("national_id","full_name","phone","date_of_birth","gender","email","membership_no","county","constituency","ward","polling_station","polling_station_code","geography_verified")}
    return redirect(url_for("candidate_home"))

@app.route("/candidate/register",methods=["GET","POST"])
def candidate_register():
    if request.method=="GET":
        return render_template("candidate_register.html")
    client_key=request.headers.get("X-Forwarded-For",request.remote_addr or "").split(",")[0].strip()
    if candidate_login_rate_limited(client_key):
        return render_template("candidate_register.html",error="Too many unsuccessful attempts. Please wait 15 minutes before trying again."),429
    national_id=request.form.get("national_id","").strip()
    phone=request.form.get("phone","").strip()
    if not national_id.isdigit() or not phone_key(phone):
        record_candidate_login_failure(client_key)
        return render_template("candidate_register.html",error="Enter a valid National ID and registered phone number."),400
    try:
        member=lookup_membership(national_id)
    except requests.RequestException:
        return render_template("candidate_register.html",error="Unable to contact the membership lookup sources. Please try again."),502
    except RuntimeError as exc:
        return render_template("candidate_register.html",error=str(exc)),500
    registered_phone=phone_key((member or {}).get("phone",""))
    if not member or not registered_phone or not hmac.compare_digest(registered_phone,phone_key(phone)):
        record_candidate_login_failure(client_key)
        return render_template("candidate_register.html",error="The National ID and phone number do not match the membership record."),403
    party_code=active_candidate_party_code()
    existing=existing_candidate_for_national_id(national_id,party_code=party_code)
    if existing:
        return render_template("candidate_register.html",error=f"This National ID already has candidate application {existing.candidate_id}. Use View Application Status to open it."),409
    if candidate_list_is_final():
        return render_template("candidate_list_final.html"),423
    _CANDIDATE_LOGIN_ATTEMPTS.pop(client_key,None)
    session.clear()
    session["candidate_national_id"]=national_id
    session["candidate_party_code"]=party_code
    session["candidate_member"]={k:(member.get(k,False) if k=="geography_verified" else str(member.get(k,"") or "")) for k in ("national_id","full_name","phone","date_of_birth","gender","email","membership_no","county","constituency","ward","polling_station","polling_station_code","geography_verified")}
    return redirect(url_for("candidate_new"))

@app.get("/odm/candidate/register")
def odm_candidate_register():
    if active_candidate_party_code()!="ODM":
        return render_template("candidate_register.html",error="ODM candidate registration is not active. Ask the administrator to select ODM branding first."),409
    return redirect(url_for("candidate_register"))

@app.get("/uda/candidate/register")
def uda_candidate_register():
    if active_candidate_party_code()!="UDA":
        return render_template("candidate_register.html",error="UDA candidate registration is not active. Ask the administrator to select UDA branding first."),409
    return redirect(url_for("candidate_register"))

@app.get("/candidate/logout")
def candidate_logout():
    session.clear()
    return redirect(url_for("candidate_access"))

@app.get("/candidate/my-application")
def candidate_home():
    if not candidate_logged_in():
        return redirect(url_for("candidate_access"))
    existing=existing_candidate_for_national_id(candidate_session_national_id())
    if existing:
        return redirect(url_for("candidate_edit",candidate_id=existing.id))
    return redirect(url_for("candidate_register"))

@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.get("/")
def dashboard():
    if not logged_in():
        if candidate_logged_in():
            return redirect(url_for("candidate_home"))
        return redirect(url_for("candidate_access"))
    selected_filters={
        "county":request.args.get("county","").strip()[:160],
        "constituency":request.args.get("constituency","").strip()[:160],
        "ward":request.args.get("ward","").strip()[:160],
        "position":request.args.get("position","").strip()[:40],
    }
    party_code=active_candidate_party_code()
    # Candidate volumes can be very large. Never issue or display a nationwide
    # candidate query: an administrator must select a county first. Lower-level
    # filters may then narrow that county's saved applications, including drafts.
    county_selected=bool(selected_filters["county"])
    candidates=[]
    if county_selected:
        query=Candidate.query.filter(
            Candidate.party_code==party_code,
            func.lower(Candidate.county)==selected_filters["county"].lower(),
        )
        for field in ("constituency","ward","position"):
            value=selected_filters[field]
            if value:
                query=query.filter(func.lower(getattr(Candidate,field))==value.lower())
        candidates=query.order_by(Candidate.position,Candidate.constituency,Candidate.ward,Candidate.full_name).all()
    state=portal_state()
    return render_template(
        "dashboard.html",candidates=candidates,positions=POSITIONS,state=state,active_party_code=party_code,
        hierarchy=hierarchy_payload(),selected_filters=selected_filters,county_selected=county_selected,
        pdf_documents=PDF_DOCUMENTS,governor_pdf_document=GOVERNOR_PDF_DOCUMENT,
        plwd_pdf_document=PLWD_PDF_DOCUMENT,
        public_officer_pdf_document=PUBLIC_OFFICER_PDF_DOCUMENT,
        bankruptcy_pdf_document=BANKRUPTCY_PDF_DOCUMENT,
        appeal_review_pdf_document=APPEAL_REVIEW_PDF_DOCUMENT,
        chapter_six_appeal_pdf_document=CHAPTER_SIX_APPEAL_PDF_DOCUMENT,
        candidate_rejection_keys=candidate_rejection_keys,
        candidate_rejection_labels=candidate_rejection_labels,
        csrf_token=admin_csrf_token(),level2_configured=bool(LEVEL2_ADMIN_USERNAME and LEVEL2_ADMIN_PASSWORD_HASH),
        message=session.pop("candidate_admin_message",None),
        error=session.pop("candidate_admin_error",None)
    )

@app.post("/admin/candidate-list/finalize")
def finalize_candidate_list():
    auth=require_login()
    if auth:
        return auth
    if not valid_admin_csrf():
        abort(400)
    if not LEVEL2_ADMIN_USERNAME or not LEVEL2_ADMIN_PASSWORD_HASH:
        session["candidate_admin_error"]="Configure the Level 2 administrator credentials before marking the candidate list Final."
        return redirect(url_for("dashboard"))
    state=portal_state()
    if not state.candidate_list_final:
        state.candidate_list_final=True
        state.locked_at=time.strftime("%Y-%m-%d %H:%M:%S UTC",time.gmtime())
        state.locked_by=AUTH_USERNAME
        db.session.commit()
    session["candidate_admin_message"]="Candidate list marked FINAL. All registration and application changes are locked."
    return redirect(url_for("dashboard"))

@app.post("/admin/candidate-list/unlock")
def unlock_candidate_list():
    auth=require_login()
    if auth:
        return auth
    if not valid_admin_csrf():
        abort(400)
    username=request.form.get("level2_username","").strip()
    password=request.form.get("level2_password","")
    username_ok=bool(LEVEL2_ADMIN_USERNAME) and hmac.compare_digest(username,LEVEL2_ADMIN_USERNAME)
    try:
        password_ok=bool(LEVEL2_ADMIN_PASSWORD_HASH) and check_password_hash(LEVEL2_ADMIN_PASSWORD_HASH,password)
    except (ValueError,TypeError):
        password_ok=False
    if not username_ok or not password_ok:
        session["candidate_admin_error"]="Level 2 administrator credentials were not accepted. The candidate list remains Final and locked."
        return redirect(url_for("dashboard"))
    state=portal_state()
    state.candidate_list_final=False
    state.locked_at=None
    state.locked_by=None
    db.session.commit()
    session["candidate_admin_message"]="Level 2 administrator unlocked the candidate list. Editing is available again."
    return redirect(url_for("dashboard"))

@app.post("/candidate/<int:candidate_id>/decision")
def candidate_decision(candidate_id):
    auth=require_login()
    if auth:
        return auth
    return_filters={key:request.form.get(key,"").strip()[:160] for key in ("county","constituency","ward","position")}
    def return_to_filtered_dashboard():
        return redirect(url_for("dashboard",**{key:value for key,value in return_filters.items() if value}))
    if not valid_admin_csrf():
        abort(400)
    if candidate_list_is_final():
        session["candidate_admin_error"]="The candidate list is FINAL. Application decisions cannot be changed until a Level 2 administrator unlocks it."
        return return_to_filtered_dashboard()
    c=Candidate.query.get_or_404(candidate_id)
    if normalized_party_code(c.party_code)!=active_candidate_party_code():
        abort(404)
    decision=request.form.get("approval_status","").strip().lower()
    if decision not in {"pending","approved","rejected"}:
        abort(400)
    if decision=="approved" and (not c.photo or not c.photo_validated):
        session["candidate_admin_error"]="This application cannot be Accepted until the passport photo has passed validation."
        return return_to_filtered_dashboard()
    missing_documents=candidate_missing_documents(c)
    if decision=="approved" and missing_documents:
        session["candidate_admin_error"]="This application cannot be Accepted until these PDF documents are attached: "+", ".join(missing_documents)+"."
        return return_to_filtered_dashboard()
    catalog=candidate_document_catalog(c)
    allowed_rejection_keys={key for key,_label,_present in catalog}
    selected_rejection_keys={
        key for key in request.form.getlist("rejection_documents")
        if key in allowed_rejection_keys
    }
    selected_rejection_keys.update(key for key,_label,present in catalog if not present)
    if decision=="rejected" and not selected_rejection_keys:
        session["candidate_admin_error"]="Select at least one missing or unacceptable document before rejecting the application."
        return return_to_filtered_dashboard()
    if candidate_list_is_final():
        session["candidate_admin_error"]="The candidate list became FINAL. The application decision was not changed."
        return return_to_filtered_dashboard()
    previous_decision=c.approval_status
    previous_rejection_reason=c.rejection_reason
    previous_rejection_reasons=c.rejection_reasons
    c.approval_status=decision
    c.rejection_reason="document_review" if decision=="rejected" else None
    c.rejection_reasons=json.dumps(sorted(selected_rejection_keys)) if decision=="rejected" else None
    db.session.commit()
    if decision=="approved":
        try:
            set_master_membership_type(c.national_id,"Life Member")
        except Exception as exc:
            c.approval_status=previous_decision
            c.rejection_reason=previous_rejection_reason
            c.rejection_reasons=previous_rejection_reasons
            db.session.commit()
            session["candidate_admin_error"]="Candidate approval was not saved because the voters register could not be updated: "+str(exc)
            return return_to_filtered_dashboard()
    return return_to_filtered_dashboard()

@app.get("/api/hierarchy")
def api_hierarchy():
    return jsonify(hierarchy_payload())


@app.get("/api/member-lookup")
def api_member_lookup():
    if not logged_in() and not candidate_logged_in():
        return jsonify({"ok":False,"error":"Login required."}), 401

    national_id=request.args.get("national_id","").strip()
    if candidate_logged_in() and not logged_in() and not hmac.compare_digest(national_id,candidate_session_national_id()):
        return jsonify({"ok":False,"error":"You may verify only your own membership record."}),403
    if not national_id:
        return jsonify({"ok":False,"error":"Enter a National ID number."}), 400
    if not national_id.isdigit():
        return jsonify({"ok":False,"error":"National ID must contain numbers only."}), 400

    try:
        member=lookup_membership(national_id)
    except requests.RequestException:
        return jsonify({
            "ok":False,
            "error":"Unable to contact the membership lookup sources. Please try again."
        }), 502
    except RuntimeError as e:
        return jsonify({"ok":False,"error":str(e)}), 500

    if not member:
        return jsonify({
            "ok":False,
            "not_found":True,
            "error":"National ID not found in the master voters register, Kobo submissions or membership_registration.csv. The applicant must first be registered as a member before candidate registration can continue."
        }), 404

    existing=existing_candidate_for_national_id(national_id)
    if existing:
        area=(
            "National" if existing.position=="president"
            else existing.ward if existing.position=="mca"
            else existing.constituency if existing.position=="mna"
            else existing.county
        )
        return jsonify({
            "ok":False,
            "already_registered":True,
            "candidate_id":existing.candidate_id,
            "position":existing.position,
            "elective_area":area or "",
            "error":f"This National ID is already registered as candidate {existing.candidate_id} for {existing.position.upper()} in {area or 'the selected electoral area'}. One National ID can submit only one candidate application."
        }), 409

    return jsonify({"ok":True,"member":member})


@app.route("/candidate/new",methods=["GET","POST"])
def candidate_new():
    if logged_in():
        # A shared browser may still carry the administrator cookie. Explicitly
        # entering candidate registration switches to the private candidate
        # identity flow instead of bouncing back to the admin dashboard.
        session.clear()
        return redirect(url_for("candidate_register"))
    if not logged_in() and not candidate_logged_in():
        return redirect(url_for("candidate_register"))
    if candidate_logged_in() and not logged_in():
        existing=existing_candidate_for_national_id(candidate_session_national_id(),party_code=candidate_session_party_code())
        if existing:
            if request.method=="POST" and existing.approval_status=="not_submitted":
                return save_candidate(existing)
            return redirect(url_for("candidate_edit",candidate_id=existing.id))
    if candidate_list_is_final():
        if logged_in():
            session["candidate_admin_error"]="The candidate list is FINAL. New registrations are locked."
            return redirect(url_for("dashboard"))
        return render_template("candidate_list_final.html"),423
    if request.method=="GET":
        return render_candidate_form_page()
    return save_candidate(None)

@app.route("/candidate/<int:candidate_id>/edit",methods=["GET","POST"])
def candidate_edit(candidate_id):
    if logged_in():
        session["candidate_admin_error"]="Administrators cannot edit candidate details or upload candidate documents. Use Application Decision to accept or reject the application."
        return redirect(url_for("dashboard"))
    if not logged_in() and not candidate_logged_in():
        return redirect(url_for("candidate_access"))
    c=Candidate.query.get_or_404(candidate_id)
    if not candidate_can_access(c):
        abort(403)
    if request.method=="GET":
        return render_candidate_form_page(c,saved=request.args.get("saved")=="1")
    return save_candidate(c)

def save_candidate(c):
    if logged_in():
        abort(403)
    if candidate_list_is_final():
        return render_candidate_form_page(c,error="The candidate list is FINAL. No application changes are permitted until a Level 2 administrator unlocks it."),423

    # Accepted applications remain view-only. Draft, pending and rejected
    # applicants may progressively save declarations, email, biography and
    # available uploads. Identity, position and electoral area remain locked.
    if c is not None and candidate_logged_in():
        if c.approval_status=="approved":
            return render_candidate_form_page(c,error="This accepted application is view-only. No fields can be changed."),423
        if c.approval_status in {"pending","not_submitted"}:
            try:
                update_candidate_editable_fields(c,request.form)
            except ValueError as exc:
                return render_candidate_form_page(c,error=str(exc))
            cropped_photo=request.form.get("cropped_photo","").strip()
            if cropped_photo:
                try:
                    c.photo,c.photo_mime=validated_candidate_photo(cropped_photo)
                    c.photo_validated=True
                except (ValueError,RuntimeError) as exc:
                    return render_candidate_form_page(c,error=str(exc))
            try:
                save_candidate_pdf_uploads(c)
            except ValueError as exc:
                return render_candidate_form_page(c,error=str(exc))
            missing_documents=candidate_missing_documents(c)
            complete=bool(c.photo and c.photo_validated and not missing_documents)
            c.approval_status="pending" if complete else "not_submitted"
            # Record every successful applicant save, whether it is the first
            # application submission or a later amendment to a saved draft.
            c.application_date=datetime.now(timezone.utc).isoformat(timespec="seconds")
            if candidate_list_is_final():
                db.session.rollback()
                return render_candidate_form_page(c,error="The candidate list became FINAL while this update was open. Your documents were not saved."),423
            db.session.commit()
            return redirect(url_for("candidate_edit",candidate_id=c.id,saved=1))
        if c.approval_status!="rejected":
            return render_candidate_form_page(c,error="This application is not open for editing."),423

        try:
            update_candidate_editable_fields(c,request.form)
        except ValueError as exc:
            return render_candidate_form_page(c,error=str(exc))
        rejection_keys=set(candidate_rejection_keys(c))
        applicable_keys={key for key,_label,_present in candidate_document_catalog(c)}
        rejection_keys &= applicable_keys
        if not rejection_keys:
            c.rejection_reasons=None
        if "passport_photo" in rejection_keys:
            cropped_photo=request.form.get("cropped_photo","").strip()
            if cropped_photo:
                try:
                    c.photo,c.photo_mime=validated_candidate_photo(cropped_photo)
                    c.photo_validated=True
                    rejection_keys.discard("passport_photo")
                except (ValueError,RuntimeError) as exc:
                    return render_candidate_form_page(c,error=str(exc))
        try:
            uploaded_documents=save_candidate_pdf_uploads(c)
        except ValueError as exc:
            return render_candidate_form_page(c,error=str(exc))
        rejection_keys-=set(uploaded_documents)

        if candidate_list_is_final():
            db.session.rollback()
            return render_candidate_form_page(c,error="The candidate list became FINAL while this correction was open. Your document was not saved."),423
        missing_documents=candidate_missing_documents(c)
        if rejection_keys:
            c.approval_status="rejected"
            c.rejection_reason="document_review"
            c.rejection_reasons=json.dumps(sorted(rejection_keys))
        elif c.photo and c.photo_validated and not missing_documents:
            c.approval_status="pending"
            c.rejection_reason=None
            c.rejection_reasons=None
        else:
            c.approval_status="not_submitted"
            c.rejection_reason=None
            c.rejection_reasons=None
        c.application_date=datetime.now(timezone.utc).isoformat(timespec="seconds")
        db.session.commit()
        return redirect(url_for("candidate_edit",candidate_id=c.id,saved=1))

    f=request.form
    position=f.get("position","").strip()
    scope=position_scope(position)
    name=f.get("full_name","").strip()
    if not name or position not in dict((k,label) for k,label,_ in POSITIONS):
        return render_candidate_form_page(c,error="Full name and position are required.")

    is_new = c is None
    if is_new:
        # Candidate ID is system-generated and never entered by the user.
        # A temporary unique value satisfies the NOT NULL/UNIQUE constraint
        # until PostgreSQL assigns the numeric primary key.
        c=Candidate(
            candidate_id="PENDING-"+uuid.uuid4().hex,
            party_code=candidate_session_party_code(),
            full_name=name,
            position=position
        )
        db.session.add(c)
        db.session.flush()
        c.candidate_id=f"{normalized_party_code(c.party_code)}-CAND-{c.id:06d}"

    national_id=f.get("national_id","").strip()
    if candidate_logged_in() and not logged_in() and not hmac.compare_digest(national_id,candidate_session_national_id()):
        abort(403)
    if not national_id:
        return render_candidate_form_page(c,error="National ID is required and must be verified against Kobo Membership Registration.")

    duplicate=existing_candidate_for_national_id(national_id, c.id if c else None,party_code=normalized_party_code(c.party_code))
    if duplicate:
        area=(
            "National" if duplicate.position=="president"
            else duplicate.ward if duplicate.position=="mca"
            else duplicate.constituency if duplicate.position=="mna"
            else duplicate.county
        )
        return render_candidate_form_page(
            c,
            error=f"This National ID is already registered as candidate {duplicate.candidate_id} for {duplicate.position.upper()} in {area or 'the selected electoral area'}. One National ID can submit only one candidate application."
        )

    try:
        member=lookup_membership(national_id)
    except requests.RequestException:
        return render_candidate_form_page(c,error="Unable to contact the membership lookup sources. Candidate was not saved.")
    except RuntimeError as e:
        return render_candidate_form_page(c,error=str(e))

    if not member:
        return render_candidate_form_page(
            c,
            error="National ID not found in the master voters register, Kobo submissions or membership_registration.csv. The applicant must first be registered as a member."
        )

    # Membership-controlled fields come from Kobo, not manual data entry.
    c.full_name=member.get("full_name") or name
    c.national_id=national_id
    c.phone=member.get("phone","")
    c.date_of_birth=member.get("date_of_birth","")
    c.gender=member.get("gender","")
    c.email=f.get("email",member.get("email","")).strip()[:160]
    if c.email and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+",c.email):
        return render_candidate_form_page(c,error="Enter a valid email address.")
    c.membership_no=member.get("membership_no","")
    disability_answer=f.get("living_with_disability","").strip().lower()
    if not disability_answer and not is_new:
        disability_answer="yes" if c.living_with_disability else "no"
    if disability_answer not in {"yes","no"}:
        return render_candidate_form_page(c,error="Select YES or NO for Are you a Person Living with Disability?")
    c.living_with_disability=disability_answer=="yes"
    public_officer_answer=f.get("public_officer_recently_resigned","").strip().lower()
    if not public_officer_answer and not is_new:
        public_officer_answer="yes" if c.public_officer_recently_resigned else "no"
    if public_officer_answer not in {"yes","no"}:
        return render_candidate_form_page(c,error="Select YES or NO for Are you a Public Officer who has recently Resigned?")
    c.public_officer_recently_resigned=public_officer_answer=="yes"
    bankruptcy_answer=f.get("ever_declared_bankrupt","").strip().lower()
    if not bankruptcy_answer and not is_new:
        bankruptcy_answer="yes" if c.ever_declared_bankrupt else "no"
    if bankruptcy_answer not in {"yes","no"}:
        return render_candidate_form_page(c,error="Select YES or NO for Have you ever been declared bankrupt?")
    c.ever_declared_bankrupt=bankruptcy_answer=="yes"
    appeal_answer=f.get("sentence_decision_appealed","").strip().lower()
    if not appeal_answer and not is_new:
        appeal_answer="yes" if c.sentence_decision_appealed else "no"
    if appeal_answer not in {"yes","no"}:
        return render_candidate_form_page(c,error="Select YES or NO for Are You subject of a Sentence and have appealed the Decision?")
    c.sentence_decision_appealed=appeal_answer=="yes"
    chapter_six_answer=f.get("chapter_six_conviction_appealed","").strip().lower()
    if not chapter_six_answer and not is_new:
        chapter_six_answer="yes" if c.chapter_six_conviction_appealed else "no"
    if chapter_six_answer not in {"yes","no"}:
        return render_candidate_form_page(c,error="Select YES or NO for Have you ever been convicted of contravening Chapter Six of the Constitution and have appealed the Decision?")
    c.chapter_six_conviction_appealed=chapter_six_answer=="yes"
    c.position=position
    c.bio=f.get("bio","").strip()
    c.status=(f.get("status","active").strip() or "active") if logged_in() else "active"
    if logged_in():
        decision=f.get("approval_status",c.approval_status or "pending").strip().lower()
        c.approval_status=decision if decision in {"pending","approved","rejected"} else "pending"
        rejection_reason=f.get("rejection_reason",c.rejection_reason or "").strip().lower()
        if c.approval_status=="rejected" and rejection_reason!="improper_candidate_picture":
            return render_candidate_form_page(c,error="Select a rejection reason before rejecting this application.")
        c.rejection_reason=rejection_reason if c.approval_status=="rejected" else None
    elif is_new:
        c.approval_status="not_submitted"

    c.county="" if scope=="national" else f.get("county","").strip()
    c.constituency=f.get("constituency","").strip() if scope in ("constituency","ward") else ""
    c.ward=f.get("ward","").strip() if scope=="ward" else ""

    if scope=="county" and not c.county:
        return render_candidate_form_page(c,error="County is required for this position.")
    if scope=="constituency" and (not c.county or not c.constituency):
        return render_candidate_form_page(c,error="County and Constituency are required for MNA.")
    if scope=="ward" and (not c.county or not c.constituency or not c.ward):
        return render_candidate_form_page(c,error="County, Constituency and Ward are required for MCA.")

    area_error=application_area_error(position,c.county,c.constituency,c.ward,member)
    if area_error:
        return render_candidate_form_page(c,error=area_error)

    if is_new:
        # Persist a private draft before image validation. It is not visible to
        # administrators and cannot enter a ballot while not_submitted.
        c.application_date=datetime.now(timezone.utc).isoformat(timespec="seconds")
        db.session.commit()

    cropped_photo=f.get("cropped_photo","").strip()
    if cropped_photo:
        try:
            c.photo,c.photo_mime=validated_candidate_photo(cropped_photo)
            c.photo_validated=True
        except (ValueError,RuntimeError) as exc:
            return render_candidate_form_page(c,error=str(exc))
    try:
        save_candidate_pdf_uploads(c)
    except ValueError as exc:
        return render_candidate_form_page(c,error=str(exc))
    missing_documents=candidate_missing_documents(c)
    if c.photo and c.photo_validated and not missing_documents:
        c.approval_status="pending"
    else:
        c.approval_status="not_submitted"

    # A rejected candidate may correct only the document identified by the
    # administrator. A valid replacement resubmits the application for review;
    # it never approves the candidate automatically.
    if candidate_logged_in() and not logged_in() and c.approval_status=="rejected":
        if c.rejection_reason=="improper_candidate_picture" and not cropped_photo:
            return render_candidate_form_page(c,error="Select, crop and confirm a fresh passport photo before resubmitting this rejected application.")
        c.approval_status="pending"
        c.rejection_reason=None

    if candidate_list_is_final():
        db.session.rollback()
        return render_candidate_form_page(c,error="The candidate list became FINAL while this form was open. Your changes were not saved."),423
    c.application_date=datetime.now(timezone.utc).isoformat(timespec="seconds")
    db.session.commit()
    if logged_in():
        return redirect(url_for("dashboard"))
    return redirect(url_for("candidate_edit",candidate_id=c.id,saved=1))

@app.get("/candidate-photo/<int:candidate_id>")
def candidate_photo(candidate_id):
    c=Candidate.query.get_or_404(candidate_id)
    if not c.photo:
        abort(404)
    return Response(c.photo,content_type=c.photo_mime or "image/jpeg")

@app.get("/candidate-document/<int:candidate_id>/<document_key>")
def candidate_document(candidate_id,document_key):
    c=Candidate.query.get_or_404(candidate_id)
    if not candidate_can_access(c):
        abort(403)
    allowed=dict((*PDF_DOCUMENTS,GOVERNOR_PDF_DOCUMENT,PLWD_PDF_DOCUMENT,PUBLIC_OFFICER_PDF_DOCUMENT,BANKRUPTCY_PDF_DOCUMENT,APPEAL_REVIEW_PDF_DOCUMENT,CHAPTER_SIX_APPEAL_PDF_DOCUMENT))
    if document_key not in allowed:
        abort(404)
    data=getattr(c,document_key,None)
    if not data:
        abort(404)
    filename=f"{c.candidate_id}_{document_key}.pdf"
    return Response(
        data,
        content_type="application/pdf",
        headers={"Content-Disposition":f'inline; filename="{filename}"',"X-Content-Type-Options":"nosniff"}
    )

@app.get("/api/candidates")
def api_candidates():
    party_code=normalized_party_code(request.args.get("party_code") or active_candidate_party_code())
    if party_code!=active_candidate_party_code():
        return jsonify({"ok":False,"error":"The requested party is not currently active."}),409
    county=request.args.get("county","")
    constituency=request.args.get("constituency","")
    ward=request.args.get("ward","")
    rows=(Candidate.query.filter_by(status="active",approval_status="approved",party_code=party_code)
          .filter(Candidate.photo.isnot(None),Candidate.photo_validated.is_(True)).all())
    out=[]
    for c in rows:
        scope=position_scope(c.position)
        allowed=False
        if scope=="national":
            allowed=True
        elif scope=="county":
            allowed=norm(c.county)==norm(county)
        elif scope=="constituency":
            allowed=norm(c.county)==norm(county) and norm(c.constituency)==norm(constituency)
        elif scope=="ward":
            allowed=(norm(c.county)==norm(county) and norm(c.constituency)==norm(constituency) and norm(c.ward)==norm(ward))
        if allowed:
            out.append(candidate_dict(c))
    out.sort(key=lambda x:(x["position"],x["full_name"]))
    return jsonify({"party_code":party_code,"results":out})

@app.get("/api/candidates/<position>")
def api_candidates_position(position):
    party_code=normalized_party_code(request.args.get("party_code") or active_candidate_party_code())
    if party_code!=active_candidate_party_code():
        return jsonify({"ok":False,"error":"The requested party is not currently active."}),409
    county=request.args.get("county","")
    constituency=request.args.get("constituency","")
    ward=request.args.get("ward","")
    rows=(Candidate.query.filter_by(position=position,status="active",approval_status="approved",party_code=party_code)
          .filter(Candidate.photo.isnot(None),Candidate.photo_validated.is_(True)).all())
    out=[]
    scope=position_scope(position)
    for c in rows:
        allowed=(scope=="national" or
                 (scope=="county" and norm(c.county)==norm(county)) or
                 (scope=="constituency" and norm(c.county)==norm(county) and norm(c.constituency)==norm(constituency)) or
                 (scope=="ward" and norm(c.county)==norm(county) and norm(c.constituency)==norm(constituency) and norm(c.ward)==norm(ward)))
        if allowed: out.append(candidate_dict(c))
    out.sort(key=lambda x:x["full_name"])
    return jsonify({"party_code":party_code,"position":position,"results":out})

if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.getenv("PORT","5000")))
