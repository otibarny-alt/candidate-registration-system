V1.37 — CANDIDATE PHOTO BACKGROUND CHECKS REMOVED

- Removes the browser background-colour and background-complexity pre-check.
- Removes the server background edge, colour-change and busy-scene rejection.
- Candidate portraits are no longer blocked because of background colour,
  gradients, patterns, scenery, text or objects.
- Retains image decoding, minimum saved dimensions, crop confirmation, face
  detection, sensible face framing and basic blur protection.
- Retains the prominent final submission button added in V1.35.
- Updates candidate instructions and status messages to state that background
  validation is disabled.

Deploy this Candidate Registration Portal release and hard-refresh the browser
so photo_cropper.js?v=37 is loaded.
