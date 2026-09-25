V1.30 - POSTGRESQL MASTER VOTERS REGISTER LOOKUP

Candidate identity verification now reads the authoritative PostgreSQL
master_voters table before any legacy membership source.

Required Render variables:
- MASTER_REGISTER_DATABASE_URL: the Internal Database URL of the PostgreSQL
  database containing master_voters.
- MASTER_REGISTER_STRICT=true

Strict mode prevents fallback to live Kobo or membership_registration.csv.
An ID absent from master_voters is treated as unregistered, and a database
connection failure returns an availability error instead of consulting the old
register.

The V1.29 candidate-to-membership edit lock remains included.
