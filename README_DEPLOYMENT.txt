2027 CANDIDATE REGISTRATION & PROFILE PORTAL V1
================================================
TRAINING / SIMULATION SUPPORT PORTAL

PURPOSE
- Register candidate biographical data and profile photograph.
- Assign the candidate to an elective position.
- Restrict the candidate to the correct electoral area using county_main.csv.
- Expose candidate data through read-only API endpoints for use by the NON-BINDING training ballot.

ELECTIVE AREA RULES
- President: National
- Governor: County
- Senator: County
- Woman Representative: County
- MNA: Constituency
- MCA: Ward

MAIN ROUTES
/                       Admin candidate list
/candidate/new          Register candidate
/candidate/<id>/edit    Edit candidate
/api/candidates         Candidates applicable to a supplied geography
/api/candidates/<position>  Candidates for one position
/candidate-photo/<id>   Candidate profile photograph

API EXAMPLE
/api/candidates?county=kisumu&constituency=kisumu_central&ward=railways

A President appears nationally.
Governor/Senator/Woman Rep candidates appear only when county matches.
MNA appears only when county+constituency match.
MCA appears only when county+constituency+ward match.

RENDER
Build: pip install -r requirements.txt
Start: gunicorn app:app

ENVIRONMENT VARIABLES
FLASK_SECRET_KEY=<strong secret>
AUTH_USERNAME=admin
AUTH_PASSWORD_HASH=<Werkzeug password hash>
DATABASE_URL=<recommended Render Postgres internal DATABASE_URL>
COUNTY_MAIN_FILENAME=county_main.csv

IMPORTANT PERSISTENCE NOTE
Use Render PostgreSQL through DATABASE_URL for persistent candidate records and photos.
The app stores candidate photos inside the database, not on the ephemeral Render filesystem.

TRAINING / SIMULATION ONLY
This portal is designed to provide candidate profile data to the non-binding training/simulation ballot.


V1.1 POSTGRES DRIVER FIX
------------------------
Render PostgreSQL URLs normally begin with postgresql:// or postgres://.
The portal uses Psycopg 3 (package: psycopg[binary]), so app.py now converts
the Render URL to postgresql+psycopg:// before SQLAlchemy creates the engine.
This fixes: ModuleNotFoundError: No module named 'psycopg2'


V1.2 — AUTOMATIC CANDIDATE ID
-----------------------------
Candidate ID is no longer entered by the administrator.

For each new candidate the portal automatically creates:
CAND-000001
CAND-000002
CAND-000003
...

The Candidate ID is generated from the database record ID, remains unique,
and is read-only on the edit screen. National ID remains a separate candidate
biographical field and cannot be confused with the internal Candidate ID.

Existing candidate records keep their current Candidate IDs.
