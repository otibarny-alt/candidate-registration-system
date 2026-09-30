V1.35 — PHOTO SUBMISSION AND FACE-DETECTION FALLBACK

- Adds a prominent final submission button immediately below a successfully
  cropped passport-photo preview.
- Makes clear that Crop & Use Photo confirms the crop but does not by itself
  submit the candidate application.
- Adds two alternative frontal-face models for valid slightly angled faces
  that the default OpenCV model can miss.
- Stops after the first successful detector so one face is not counted once
  by each model.
- Retains V1.34 plain-background, duplicate-face, blur and busy-scene fixes.
- Continues to reject images with no detectable candidate face, genuinely
  separate multiple faces, or busy backgrounds.

Deploy this Candidate Registration Portal release and perform a hard browser
refresh so photo_cropper.js?v=35 is loaded.
