V1.38 — PRIMARY CANDIDATE FACE ONLY

- Removes automatic multiple-face rejection.
- Uses the largest detected face as the candidate's primary face.
- Ignores all additional Haar detections because patterned clothing, textured
  hair, jewellery and shadows frequently create false face boxes.
- Keeps the requirement that at least one clear candidate face is detected.
- Keeps crop dimensions, framing, readability and basic blur checks.
- Keeps all background checks disabled as requested in V1.37.
- Group-photo or suitability decisions can still be made by the candidate
  registration administrator during application review.

Deploy this Candidate Registration Portal release and hard-refresh the browser
so photo_cropper.js?v=38 is loaded.
