"""
Modal GPU deployment for the Kronos forecast service.

Deploy:
    modal deploy modal_app.py

After deploy, Modal prints a URL like:
    https://your-org--kronos-service-fastapi-app.modal.run

Set that as KRONOS_URL on Railway (or your .env) and the backtester
will automatically route forward-test path generation through Kronos.

GPU: T4 by default (cheapest, handles Kronos-small easily).
     Switch to "A10G" for Kronos-base (102M params).

Pricing (Modal pay-per-second, scale-to-zero):
    T4  ~ $0.000164 / second  →  ~$0.60 / hour
    A10G ~ $0.000583 / second →  ~$2.10 / hour
    Idle cost = $0 (scales to zero after scaledown_window)
"""
import modal

# ── Image: Debian + Python + Kronos repo + deps ───────────────────────────────
image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git")
    .run_commands(
        "git clone https://github.com/shiyu-coder/Kronos /app/Kronos",
        "pip install -r /app/Kronos/requirements.txt",
    )
    .pip_install(
        "fastapi>=0.111.0",
        "uvicorn[standard]>=0.29.0",
        "pydantic>=2.0.0",
    )
    # Copy our service code into the image
    .copy_local_file("main.py", "/app/main.py")
)

app = modal.App("kronos-service", image=image)

# Pre-download model weights into the image layer (cached between deploys)
with image.imports():
    import sys
    sys.path.insert(0, "/app/Kronos")


@app.function(
    gpu="T4",                  # T4 for Kronos-small; use "A10G" for Kronos-base
    scaledown_window=60,       # Scale to zero after 60s idle → no idle cost
    timeout=300,               # 5-min max per request (100 paths × ~2s = ~200s)
    secrets=[
        # Optional: pass HF_TOKEN if models are private
        # modal.Secret.from_name("huggingface-token"),
    ],
)
@modal.asgi_app()
def fastapi_app():
    import sys
    sys.path.insert(0, "/app/Kronos")

    # Patch the service to use CUDA
    import os
    os.environ.setdefault("KRONOS_DEVICE", "cuda")
    os.environ.setdefault("KRONOS_MODEL",  "NeoQuasar/Kronos-small")

    # Import after patching env so the model loads on GPU
    sys.path.insert(0, "/app")
    from main import app as fastapi_application
    return fastapi_application
