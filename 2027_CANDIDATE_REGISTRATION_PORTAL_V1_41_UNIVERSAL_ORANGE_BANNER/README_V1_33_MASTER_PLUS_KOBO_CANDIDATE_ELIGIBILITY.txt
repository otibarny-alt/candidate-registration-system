V1.33 — MASTER PLUS KOBO CANDIDATE ELIGIBILITY

Candidate membership verification now checks the PostgreSQL master voters
register first. If the National ID is not present there, it checks the earlier
live Kobo Membership Registration submissions and membership_registration.csv.

This permits valid members registered before the master-database migration to
apply as candidates. When the same National ID exists in the master register,
the master record remains authoritative. MASTER_REGISTER_STRICT still fails
closed when the master database is configured but unavailable.
