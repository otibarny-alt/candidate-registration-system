V1.28 — CLEAN TEST RESET SUPPORT

Adds a private server-to-server reset endpoint used by the voting-system Admin
Data Files page. It deletes all candidate applications and unlocks the final
candidate list. The endpoint is disabled unless SYSTEM_RESET_TOKEN is set and
requires the same Bearer token configured on the voting service.
