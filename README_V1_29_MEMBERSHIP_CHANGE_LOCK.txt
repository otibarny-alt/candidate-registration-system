V1.29 - CANDIDATE MEMBERSHIP CHANGE LOCK

Adds a protected service-to-service endpoint that reports whether a National ID
has any candidate registration record. The check deliberately includes every
position, status, and decision state so draft, pending, accepted, rejected,
active, and inactive candidate records all lock membership corrections.

Authentication uses CANDIDATE_ELIGIBILITY_TOKEN. If that variable is omitted,
the existing shared SYSTEM_RESET_TOKEN is used for backward-compatible setup.
