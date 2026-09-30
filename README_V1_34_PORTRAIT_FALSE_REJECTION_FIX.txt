V1.34 — VALID PORTRAIT FALSE-REJECTION FIX

- Accepts clear single-person passport portraits on a plain background of any
  colour, including portraits where hair or shoulders approach crop edges.
- Excludes the detected person's hair, ears, clothing and shoulders from the
  server background-complexity measurement.
- Merges overlapping face-detection boxes belonging to the same person while
  continuing to reject genuinely separate faces.
- Allows clear low-resolution source portraits that the cropper safely
  enlarges, without removing the minimum saved-image dimensions.
- Browser pre-validation now examines genuine corner background areas instead
  of treating the candidate's hair or jacket as background activity.
- Busy scenery, text, patterned backgrounds, multiple people and images with
  no detected candidate face remain rejected.

Deploy this Candidate Registration Portal release. Browsers receive the new
photo validator through an updated cache-busting script version.
