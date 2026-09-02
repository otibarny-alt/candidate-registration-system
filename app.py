
import os, csv, re, uuid
from io import BytesIO
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, Response, abort
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash

app=Flask(__name__)
app.secret_key=os.getenv("FLASK_SECRET_KEY","candidate-portal-change-me")

db_url=os.getenv("DATABASE_URL","sqlite:///candidates.db")
# Render provides a PostgreSQL URL without an explicit driver.
# This application installs Psycopg 3, so tell SQLAlchemy to use it.
if db_url.startswith("postgres://"):
    db_url="postgresql+psycopg://"+db_url[len("postgres://"):]
elif db_url.startswith("postgresql://"):
    db_url="postgresql+psycopg://"+db_url[len("postgresql://"):]
app.config["SQLALCHEMY_DATABASE_URI"]=db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"]=False
app.config["MAX_CONTENT_LENGTH"]=6*1024*1024
db=SQLAlchemy(app)

COUNTY_MAIN=os.getenv("COUNTY_MAIN_FILENAME","county_main.csv")
AUTH_USERNAME=os.getenv("AUTH_USERNAME","admin")
AUTH_PASSWORD_HASH=os.getenv("AUTH_PASSWORD_HASH","")

POSITIONS=[
 ("president","President","national"),
 ("governor","Governor","county"),
 ("senator","Senator","county"),
 ("woman_rep","Woman Representative","county"),
 ("mna","MNA","constituency"),
 ("mca","MCA","ward"),
]

class Candidate(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    candidate_id=db.Column(db.String(80),unique=True,nullable=False,index=True)
    full_name=db.Column(db.String(180),nullable=False)
    national_id=db.Column(db.String(40))
    phone=db.Column(db.String(40))
    email=db.Column(db.String(160))
    membership_no=db.Column(db.String(100))
    position=db.Column(db.String(40),nullable=False,index=True)
    county=db.Column(db.String(160),index=True)
    constituency=db.Column(db.String(160),index=True)
    ward=db.Column(db.String(160),index=True)
    bio=db.Column(db.Text)
    photo=db.Column(db.LargeBinary)
    photo_mime=db.Column(db.String(80))
    status=db.Column(db.String(20),default="active",nullable=False,index=True)

with app.app_context():
    db.create_all()

def logged_in():
    return bool(session.get("admin"))

def require_login():
    if not logged_in():
        return redirect(url_for("login"))
    return None

def norm(v):
    return re.sub(r"[^a-z0-9]+","_",str(v or "").strip().lower()).strip("_")

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

def position_scope(position):
    return dict((k,scope) for k,_,scope in POSITIONS).get(position,"national")

def candidate_dict(c):
    return {
      "id":c.id,
      "candidate_id":c.candidate_id,
      "full_name":c.full_name,
      "national_id":c.national_id or "",
      "phone":c.phone or "",
      "email":c.email or "",
      "membership_no":c.membership_no or "",
      "position":c.position,
      "county":c.county or "",
      "constituency":c.constituency or "",
      "ward":c.ward or "",
      "bio":c.bio or "",
      "status":c.status,
      "photo_url":url_for("candidate_photo",candidate_id=c.id,_external=True) if c.photo else None
    }

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
    session["admin"]=True
    return redirect(url_for("dashboard"))

@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.get("/")
def dashboard():
    if not logged_in():
        return redirect(url_for("login"))
    candidates=Candidate.query.order_by(Candidate.position,Candidate.county,Candidate.constituency,Candidate.ward,Candidate.full_name).all()
    return render_template("dashboard.html",candidates=candidates,positions=POSITIONS)

@app.get("/api/hierarchy")
def api_hierarchy():
    return jsonify(hierarchy_payload())

@app.route("/candidate/new",methods=["GET","POST"])
def candidate_new():
    r=require_login()
    if r:return r
    if request.method=="GET":
        return render_template("candidate_form.html",candidate=None,positions=POSITIONS)
    return save_candidate(None)

@app.route("/candidate/<int:candidate_id>/edit",methods=["GET","POST"])
def candidate_edit(candidate_id):
    r=require_login()
    if r:return r
    c=Candidate.query.get_or_404(candidate_id)
    if request.method=="GET":
        return render_template("candidate_form.html",candidate=c,positions=POSITIONS)
    return save_candidate(c)

def save_candidate(c):
    f=request.form
    position=f.get("position","").strip()
    scope=position_scope(position)
    name=f.get("full_name","").strip()
    if not name or position not in dict((k,label) for k,label,_ in POSITIONS):
        return render_template("candidate_form.html",candidate=c,positions=POSITIONS,error="Full name and position are required.")

    is_new = c is None
    if is_new:
        # Candidate ID is system-generated and never entered by the user.
        # A temporary unique value satisfies the NOT NULL/UNIQUE constraint
        # until PostgreSQL assigns the numeric primary key.
        c=Candidate(
            candidate_id="PENDING-"+uuid.uuid4().hex,
            full_name=name,
            position=position
        )
        db.session.add(c)
        db.session.flush()
        c.candidate_id=f"CAND-{c.id:06d}"

    c.full_name=name
    c.national_id=f.get("national_id","").strip()
    c.phone=f.get("phone","").strip()
    c.email=f.get("email","").strip()
    c.membership_no=f.get("membership_no","").strip()
    c.position=position
    c.bio=f.get("bio","").strip()
    c.status=f.get("status","active").strip() or "active"

    c.county="" if scope=="national" else f.get("county","").strip()
    c.constituency=f.get("constituency","").strip() if scope in ("constituency","ward") else ""
    c.ward=f.get("ward","").strip() if scope=="ward" else ""

    if scope=="county" and not c.county:
        return render_template("candidate_form.html",candidate=c,positions=POSITIONS,error="County is required for this position.")
    if scope=="constituency" and (not c.county or not c.constituency):
        return render_template("candidate_form.html",candidate=c,positions=POSITIONS,error="County and Constituency are required for MNA.")
    if scope=="ward" and (not c.county or not c.constituency or not c.ward):
        return render_template("candidate_form.html",candidate=c,positions=POSITIONS,error="County, Constituency and Ward are required for MCA.")

    photo=request.files.get("photo")
    if photo and photo.filename:
        if not (photo.mimetype or "").startswith("image/"):
            return render_template("candidate_form.html",candidate=c,positions=POSITIONS,error="Candidate photo must be an image.")
        c.photo=photo.read()
        c.photo_mime=photo.mimetype or "image/jpeg"

    db.session.commit()
    return redirect(url_for("dashboard"))

@app.post("/candidate/<int:candidate_id>/delete")
def candidate_delete(candidate_id):
    r=require_login()
    if r:return r
    c=Candidate.query.get_or_404(candidate_id)
    db.session.delete(c)
    db.session.commit()
    return redirect(url_for("dashboard"))

@app.get("/candidate-photo/<int:candidate_id>")
def candidate_photo(candidate_id):
    c=Candidate.query.get_or_404(candidate_id)
    if not c.photo:
        abort(404)
    return Response(c.photo,content_type=c.photo_mime or "image/jpeg")

@app.get("/api/candidates")
def api_candidates():
    county=request.args.get("county","")
    constituency=request.args.get("constituency","")
    ward=request.args.get("ward","")
    rows=Candidate.query.filter_by(status="active").all()
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
    return jsonify({"results":out})

@app.get("/api/candidates/<position>")
def api_candidates_position(position):
    county=request.args.get("county","")
    constituency=request.args.get("constituency","")
    ward=request.args.get("ward","")
    rows=Candidate.query.filter_by(position=position,status="active").all()
    out=[]
    scope=position_scope(position)
    for c in rows:
        allowed=(scope=="national" or
                 (scope=="county" and norm(c.county)==norm(county)) or
                 (scope=="constituency" and norm(c.county)==norm(county) and norm(c.constituency)==norm(constituency)) or
                 (scope=="ward" and norm(c.county)==norm(county) and norm(c.constituency)==norm(constituency) and norm(c.ward)==norm(ward)))
        if allowed: out.append(candidate_dict(c))
    out.sort(key=lambda x:x["full_name"])
    return jsonify({"position":position,"results":out})

if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.getenv("PORT","5000")))
