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


V1.3 — KOBO MEMBERSHIP LOOKUP GATE
----------------------------------
Candidate registration now begins with National ID membership verification.

When a National ID is entered:
1. The portal queries the Kobo Membership Registration Database using:
   basics/national_id_no
2. If a member is found, the portal fills Full Name, Phone, Email and Membership No.
3. Those membership-controlled fields are read-only in the candidate form.
4. If the ID is not found, candidate registration is blocked and the user is told
   that the applicant must first be registered as a member.
5. The server repeats the Kobo check during Save; the browser check cannot be bypassed.

Render environment variables required:
KOBO_BASE_URL=https://kf.kobotoolbox.org
MEMBERSHIP_ASSET_UID=<Membership Registration Kobo asset UID>
KOBO_API_TOKEN=<Kobo API token>

Known Membership Registration fields used:
basics/national_id_no
members_particulars/first_name
members_particulars/other_names
members_particulars/surname
members_particulars/odm_membership_no

For phone and email the portal checks several common field paths so it remains tolerant
of naming differences in the Membership Registration form.


V1.4 — NATIONAL ID FIRST
------------------------
The registration form now starts with National ID.

Workflow:
1. Enter National ID first.
2. Click Lookup Member.
3. Portal queries Kobo Membership Registration.
4. If found: Full Name, Phone, Email and Membership No. are populated automatically.
5. If not found: registration is blocked and the portal instructs the applicant to register as a member first.
6. Candidate ID is still system-generated only after the candidate is saved.


V1.5 — CANDIDATE DELETION DISABLED
----------------------------------
The Delete link has been removed from the Registered Candidates screen.
The server-side candidate deletion endpoint has also been removed.

Candidate records can still be corrected using Edit, and status can be changed
to Inactive where a candidate should no longer be active. This prevents accidental
permanent deletion of submitted candidate profiles.


V1.6 — IN-BROWSER PHOTO CROPPER
-------------------------------
Candidate photos can now be cropped before saving.

Workflow:
1. Select candidate photo.
2. A 4:5 portrait crop frame appears.
3. Drag the photo to reposition it.
4. Use the Zoom slider if necessary.
5. Click Confirm Crop.
6. The cropped JPEG is saved to the database when the candidate is saved.

The crop is fixed at 400 x 500 pixels (4:5 portrait), giving consistent candidate
photos for the candidate portal and training/simulation ballot display.


V1.7 — RELIABLE PHOTO CROPPER
-----------------------------
The cropper has been separated into its own JavaScript file so that any error in the
membership/hierarchy form script cannot prevent photo cropping.

When a photo is selected:
- the crop frame opens automatically;
- the page scrolls to the crop frame;
- the candidate can drag and zoom the image;
- "Crop & Use Photo" creates a visible final preview;
- the form refuses to save a newly selected photo until the crop has been confirmed.

The visible "Cropped photo to be saved" preview is the exact 400 x 500 JPEG sent to the server.
The JavaScript file is loaded with ?v=17 to reduce browser-cache problems after deployment.


V1.8 — MEMBERSHIP NUMBER ON CANDIDATE LIST
------------------------------------------
The Registered Candidates table now includes a dedicated Membership No. column.
The number displayed is the membership number already pulled from Kobo Membership Registration
when the candidate was verified.
