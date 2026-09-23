V1.25.2 — RENDER OPENCV DEPENDENCY FIX

RapidOCR declares the desktop opencv-python package as a dependency. Installing
it alongside opencv-python-headless caused both packages to overwrite the same
cv2 module on Render, producing:

  AttributeError: module 'cv2' has no attribute 'CascadeClassifier'

The Render build now installs RapidOCR 1.4.4 without its automatic dependencies
after explicitly installing the complete headless dependency set. This leaves
only opencv-python-headless in the environment. A build-time verification script
checks CascadeClassifier, the face cascade, ONNX Runtime and RapidOCR before
Gunicorn is allowed to start.
