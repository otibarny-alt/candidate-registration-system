V1.27 — PASSPORT-PHOTO-ONLY APPLICATIONS

- Removes the Payment Evidence upload, viewer, OCR validation, payment-specific
  rejection reason, and payment dependencies.
- The passport photo is the only application upload.
- A candidate application remains NOT SUBMITTED until its passport photo passes
  server validation, then moves to PENDING APPROVAL.
- Records the first successful submission time in application_date and displays
  it as Application Date on the administrator approval page.
- Existing database payment columns are left untouched for safe deployment, but
  this version no longer reads, writes, displays, or requires them.

Render build command:
pip install -r requirements.txt && python verify_runtime.py
