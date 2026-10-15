Candidate Registration Portal V1.54
===================================

This release makes the Main Navigation and all Candidate Registration pages
use the active party branding selected in the central Voting System. Each
template now selects the shared banner directly. If the HTTP branding service
cannot be reached, the application reads app_party_branding from the shared
PostgreSQL database and uses the bundled, exact UDA banner.

Render configuration
--------------------
Set this environment variable on the Candidate Registration service:

PARTY_BRANDING_API_URL=https://voting-simulation-system.onrender.com/api/party-branding

Replace the hostname if your central Voting System uses a different address.
Redeploy the Candidate Registration service after setting the variable.

Verification
------------
Open this address on the Candidate Registration service:

/api/party-branding-status

The response must show:
- "ok": true
- the correct source_url
- "code": "UDA" after UDA is selected centrally
- a non-empty header_url

The server refreshes branding every 10 seconds. Open pages also check every
10 seconds, so Main Navigation and candidate pages update without a restart.
