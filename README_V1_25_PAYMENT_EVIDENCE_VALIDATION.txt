V1.25 — PAYMENT EVIDENCE OCR VALIDATION

Payment Evidence is now OCR-validated before it can be saved. Accepted evidence
is limited to a complete M-Pesa confirmation containing a structurally valid
10-character M-Pesa code, a bank cheque with readable cheque details, or a
successful credit-card payment confirmation with a readable reference.

Extracted payment references are stored separately and protected by a unique
database index so the same evidence cannot be reused for another candidate.
Unmasked card numbers are rejected; applicants must use a confirmation showing
only masked digits and the last four digits.

OCR/document checks verify the evidence type and reference format. Final proof
of settlement remains part of administrator review. Confirming an M-Pesa code
against Safaricom itself requires separately authorized Daraja transaction
status credentials and is not performed by this release.
