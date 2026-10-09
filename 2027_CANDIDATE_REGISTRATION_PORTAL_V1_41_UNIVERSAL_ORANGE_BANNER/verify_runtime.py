"""Fail the Render build early if the passport-photo runtime is incomplete."""
import os

import cv2
import numpy

required=("CascadeClassifier","imdecode","cvtColor","Laplacian")
missing=[name for name in required if not hasattr(cv2,name)]
if missing:
    raise RuntimeError("OpenCV runtime is incomplete; missing: "+", ".join(missing))

cascade_path=os.path.join(cv2.data.haarcascades,"haarcascade_frontalface_default.xml")
if not os.path.isfile(cascade_path) or cv2.CascadeClassifier(cascade_path).empty():
    raise RuntimeError("OpenCV face-detection cascade is missing or unreadable.")

print("Runtime verification passed:")
print("  NumPy",numpy.__version__)
print("  OpenCV",cv2.__version__)
print("  Face cascade OK")
