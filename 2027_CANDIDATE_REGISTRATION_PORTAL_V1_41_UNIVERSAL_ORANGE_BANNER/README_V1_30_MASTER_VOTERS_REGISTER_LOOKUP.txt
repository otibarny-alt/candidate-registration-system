V1.30 - POSTGRESQL MASTER VOTERS REGISTER LOOKUP

Candidate identity verification now reads the authoritative PostgreSQL
master_voters table before any legacy membership source.

Required Render variables:
- MASTER_REGISTER_DATABASE_URL: the Internal Database URL of the PostgreSQL
  database containing master_voters.
- MASTER_REGISTER_STRICT=true

Strict mode fails closed when the master database cannot be contacted. When the
database is reachable but an ID is absent from master_voters, the portal checks
live Kobo and membership_registration.csv for valid pre-migration members.

The V1.29 candidate-to-membership edit lock remains included.
V1.33 NOTE: A reachable master-register miss now falls through to the earlier
Kobo/CSV membership sources so valid pre-migration members may register as
candidates. A master-database connection failure still fails closed in strict
mode.
