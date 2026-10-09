V1.36 — FALSE MULTIPLE-FACE REJECTION FIX

- Treats the largest detected central face as the candidate.
- Ignores small false detections caused by textured hair, jacket lapels,
  jewellery, clothing patterns and shadows.
- Rejects an image as multiple-person only when a second distinct detection is
  at least 30 percent of the candidate face and lies in a plausible head area.
- Retains all V1.34 and V1.35 background, crop, submission and fallback face
  detection improvements.
- Images with no candidate face, a genuinely second candidate-sized face, or
  a busy background remain blocked.

Deploy this Candidate Registration Portal release and hard-refresh the browser
so photo_cropper.js?v=36 is loaded.
