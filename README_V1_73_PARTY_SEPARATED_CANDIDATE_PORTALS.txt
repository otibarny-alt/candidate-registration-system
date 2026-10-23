2027 CANDIDATE REGISTRATION PORTAL V1.73

ODM / UDA CANDIDATE SEPARATION

- Adds an immutable party_code to every candidate application.
- Existing candidate records are migrated to ODM.
- New applications inherit the party currently selected in Admin Data Files.
- The same National ID may have one ODM application and one UDA application,
  while duplicate applications within the same party remain blocked.
- Candidate access, administrator review, approval, final-list locking and the
  candidate API are isolated by party.
- ODM and UDA have independent Final/Unlocked candidate-list states.
- Dedicated entry addresses:
    /odm/candidate/register
    /uda/candidate/register
- The active-party API returns only candidates belonging to the requested
  party and identifies that party in its response.

Deploy this portal together with Voting System V23.252.
