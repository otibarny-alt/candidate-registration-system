V1.25.1 — RENDER PYTHON BUILD FIX

Render's current default Python 3.14 runtime is not compatible with the
RapidOCR/ONNX Runtime release used for payment-evidence validation.

This release pins the candidate portal to Python 3.12 in .python-version and
to Python 3.12.14 in render.yaml. This allows RapidOCR and ONNX Runtime to
install while retaining the V1.24 photo checks and V1.25 payment checks.
