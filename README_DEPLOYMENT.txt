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


V1.10 — ONE NATIONAL ID = ONE CANDIDATE APPLICATION
----------------------------------------------------
A National ID can now appear in only one candidate application across the entire portal.

This rule applies regardless of:
- elective position;
- county;
- constituency;
- ward.

Examples now blocked:
- the same National ID applying for MCA and later MNA;
- the same National ID applying in two different wards;
- the same National ID applying in two different constituencies;
- the same National ID applying in two different counties.

When National ID lookup is performed, the portal checks:
1. that the person exists in the Membership Registration Database; and
2. that the National ID is not already attached to another candidate record.

If already registered, the portal displays the existing Candidate ID, position and elective area
and blocks the new application.

The same check is repeated server-side during Save, so it cannot be bypassed from the browser.

Editing an existing candidate remains allowed. Editing changes the one existing application rather
than creating another application for the same National ID.

IMPORTANT FOR EXISTING DATA:
V1.10 does not automatically delete or merge duplicate records that were already created in older
versions. Those records remain visible so an administrator can review and correct them safely.
New duplicates are blocked from V1.10 onward.


V1.11 — PAYMENT EVIDENCE IMAGE
--------------------------------
- Adds a required Payment Evidence image to new candidate applications.
- Accepts validated JPG, PNG and WebP images up to 5 MB.
- Stores payment evidence in PostgreSQL alongside the candidate record, so it survives redeployments.
- Existing applications without evidence must upload it when next edited.
- Logged-in administrators can open the saved evidence from the candidate list or edit screen.
- The public candidate API does not expose or load payment-evidence images.
- Existing databases are upgraded automatically with the new payment-evidence columns during deployment.


V1.12 — PRIVATE CANDIDATE SELF-SERVICE
--------------------------------------
- The registered-candidate list at / is administrator-only.
- Candidates enter through /candidate-access using National ID plus the phone number held in Kobo Membership Registration.
- Candidate sessions are bound to one National ID and can view or edit only that candidate's application.
- Server-side ownership checks block direct URL attempts to edit another candidate or view another candidate's payment evidence.
- Candidate status remains an administrator-only field.
- Candidates never return to the full candidate list after saving; they return to their own private application.
- Failed candidate-login attempts are rate-limited.
- The existing administrator username/password and full candidate-management screen remain unchanged.

No new environment variables are required. Candidate access uses the existing
KOBO_BASE_URL, MEMBERSHIP_ASSET_UID and KOBO_API_TOKEN connection.


V1.13 — CANDIDATE VOTER-AREA ELIGIBILITY
----------------------------------------
- Resolves each candidate's registered county, constituency and ward from Kobo Membership Registration and county_main.csv.
- Uses the polling-station code first, preventing confusion where polling-station names repeat in different counties.
- Governor, Senator and Woman Representative applicants may apply only in their registered voter county.
- MNA applicants may apply only in their registered voter constituency.
- MCA applicants may apply only in their registered voter ward and constituency.
- Presidential applicants may be registered voters anywhere in the country.
- Candidate self-service lists only the applicant's eligible county, constituency and ward.
- The server repeats all eligibility checks during every save, preventing browser or URL manipulation.
- If voter geography cannot be verified unambiguously, non-presidential registration is blocked until the membership/voter record is corrected.

No new environment variables are required.


V1.13.1 — POST-DEPLOYMENT SESSION COMPATIBILITY FIX
---------------------------------------------------
- Fixes the candidate edit-page HTTP 500 seen by candidates who remained logged in during the V1.13 deployment.
- Older sessions are automatically refreshed with the new voter-area fields from Kobo.
- Missing session fields now receive safe defaults and cannot break template rendering.
- If Kobo is temporarily unavailable during refresh, the page displays a sign-in instruction instead of an internal server error.

V1.14 — CANCEL EDIT CONTROLS
----------------------------

- Adds a Cancel Edit button that discards unsaved changes and returns candidates to their private application page or administrators to the candidate list.
- Adds a Cancel Photo Change button to clear a newly selected or cropped image while retaining the currently saved candidate photo.

V1.15 — ADMINISTRATOR APPLICATION DECISIONS
-------------------------------------------

- Adds Pending, Approved and Rejected application decisions controlled only by an authenticated administrator.
- Existing and newly submitted applications default to Pending and therefore do not enter a ballot automatically.
- Candidate users can see their current decision but cannot alter it.
- Both public candidate API routes return only candidates whose records are Active and whose applications are Approved.
- Administrators can update decisions directly from the registered-candidates list or from the candidate edit page.

V1.15.1 — APPLICATION DECISION DISPLAY
--------------------------------------

- Moves Application Decision to the final column of the administrator candidate list.
- Displays Pending in orange, Accepted in green and Rejected in red.
- Updates the colour immediately when an administrator changes the selection.

V1.15.2 — DECISION UPDATE CONFIRMATION
-------------------------------------

- Shows a grey, disabled “✓ Updated” button when the displayed decision is already saved.
- Changes the button to a blue, active “✕ Update” control when an administrator selects a different decision.
- Returning the selector to its saved value restores “✓ Updated” without sending an unnecessary update.
- Shows “Updating…” while a changed decision is being saved.

V1.15.3 — REGISTRATION HEADER PRIVACY
--------------------------------------

- Removes the Back to Candidates link from the candidate registration and edit page header.
- Candidate-list access remains available only through protected administrator navigation.

V1.16 — FINAL CANDIDATE LIST CENTRAL LOCK
----------------------------------------

- An authenticated administrator can mark the complete candidate list Final.
- Final status is stored in PostgreSQL and therefore survives restarts and deployments.
- While Final, new registrations, candidate edits, record-status changes and application-decision changes are blocked both in the interface and on the server.
- Approved, active candidates remain available to ballot feeds while the list is locked.
- Only valid Level 2 credentials can unlock the list.
- The system refuses to finalize unless LEVEL2_ADMIN_USERNAME and LEVEL2_ADMIN_PASSWORD_HASH are configured.

V1.16.1 — REQUIRED APPLICATION IMAGES
-------------------------------------

- Candidate applications cannot be saved without both a confirmed candidate photo and validated payment-evidence image.
- Administrators cannot mark an incomplete application Accepted.
- Approved-only ballot feeds independently require both stored images.
- Accepted legacy records missing either image are returned to Pending during deployment for completion and fresh review.
V1.17 — KOBO MEDIA MEMBERSHIP FALLBACK

Candidate identity lookup now checks live Kobo submissions first and then
membership_registration.csv in the Membership Registration project's Kobo media.
An applicant is treated as unregistered only after both sources return no match.
CSV matches supply the member name, phone, email, membership number, county,
constituency, ward and polling station used by the existing application restrictions.

Optional Render variables:
MEMBERSHIP_CSV_FILENAME=membership_registration.csv
MEMBERSHIP_CSV_CACHE_SECONDS=300
V1.18 — CANDIDATE STATUS AND REJECTED-DOCUMENT RESUBMISSION

- Candidates use the private Candidate Access page and verify their National ID
  with the phone number held in membership registration.
- Their own application then clearly shows Pending Approval, Accepted or
  Rejected. No candidate list or another applicant's data is exposed.
- An administrator must select a rejection reason: Faulty payment evidence or
  Improper candidate picture.
- A rejected candidate can upload the specified replacement document and Save,
  or leave without changing anything by using Cancel Edit / Cancel Photo Change.
- A valid correction returns the application to Pending Approval for a fresh
  administrator review; it never approves the application automatically.
- The FINAL candidate-list lock continues to prevent all candidate and admin
  edits until a Level 2 administrator unlocks it.
V1.19 — CANDIDATE SELF-SERVICE LINK AND ADMIN REVIEW-ONLY ROLE

- The registration page has a prominent "Already registered? View Status / Edit
  Application" link. Candidates sign in with National ID and registered phone.
- Administrators can review applications and record Pending, Accepted or
  Rejected decisions, including a rejection reason.
- Administrator candidate creation, profile editing and document uploading are
  blocked in both the interface and server routes. Candidate details, photos
  and payment evidence must be submitted or corrected by the candidate.
V1.19.1 — ADMIN-SESSION CANDIDATE ENTRY FIX

- Opening /candidate/new while an administrator is signed in now switches to
  the private National ID and phone verification page instead of redirecting
  back to the administrator dashboard.
- After verification, a first-time candidate receives the new application form;
  an already registered candidate receives only their own status/edit page.
V1.20 — STATUS-BASED FIELD LOCKING

- Pending and Accepted applications are completely view-only.
- A rejection for Faulty payment evidence opens only Payment Evidence.
- A rejection for Improper candidate picture opens only Candidate Photo.
- Candidate particulars and the unrelated document remain locked during every
  correction. The server enforces the same rule even if a browser request is
  manually altered.
- Submitting the permitted correction returns the application to Pending.
