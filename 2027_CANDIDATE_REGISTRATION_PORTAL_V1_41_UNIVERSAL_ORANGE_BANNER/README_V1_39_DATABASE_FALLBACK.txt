V1.39 - Candidate Database URL Fallback

The Candidate Registration service now selects its database in this order:

1. CANDIDATE_DATABASE_URL
2. MASTER_REGISTER_DATABASE_URL
3. DATABASE_URL
4. Local SQLite only when no PostgreSQL URL is configured

This restores the portal when the old DATABASE_URL contains an expired or
unresolvable Render hostname but the master-register database is available.
Candidate, portal-state and approval tables are created automatically in the
selected database.

Database failures during requests now show a branded recovery page instead of
the generic white Internal Server Error screen. API failures return JSON 503.
