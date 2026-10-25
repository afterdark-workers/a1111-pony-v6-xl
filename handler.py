"""RunPod Serverless handler for AUTOMATIC1111 Stable Diffusion WebUI.

The webui runs API-only on 127.0.0.1:7860 inside the worker. A job's `input` is sent to /sdapi/v1/txt2img as is
(prompt, negative_prompt, seed, width, height, steps, cfg_scale, sampler_name, scheduler, override_settings …),
and the pictures come back like the ComfyUI worker's: output.images = [{filename, type: "base64", data}].
"""
import glob
import os
import subprocess
import sys
import time

# run in the handler's own Python (see build.sh); the webui keeps the image's Python
if sys.prefix != "/rp":
    os.execv("/rp/bin/python", ["/rp/bin/python", "-u", __file__])

import requests
import runpod

API = "http://127.0.0.1:7860"
CKPT = sorted(glob.glob("/webui/models/Stable-diffusion/*.safetensors"))[0]

webui = subprocess.Popen(
    ["/usr/local/bin/python", "launch.py", "--skip-prepare-environment", "--skip-install", "--skip-version-check",
     "--nowebui", "--api", "--port", "7860", "--no-download-sd-model", "--no-hashing",
     "--opt-sdp-attention", "--no-half-vae", "--ckpt", CKPT],
    cwd="/webui", env={**os.environ, "HF_HOME": "/hf"},
)


def wait_ready():
    while True:
        if webui.poll() is not None:
            raise RuntimeError(f"the webui stopped (exit {webui.returncode}) — see the worker log")
        try:
            if requests.get(API + "/sdapi/v1/sd-models", timeout=5).ok:
                return
        except requests.RequestException:
            pass
        time.sleep(0.5)


def handler(job):
    inp = dict(job.get("input") or {})
    if not inp.get("prompt"):
        return {"error": "input.prompt is required"}
    inp.update(save_images=False, send_images=True)
    wait_ready()
    r = requests.post(API + "/sdapi/v1/txt2img", json=inp, timeout=900)
    if not r.ok:
        return {"error": f"txt2img {r.status_code}: {r.text[:500]}"}
    images = r.json().get("images") or []
    return {"images": [{"filename": f"{job['id']}_{i}.png", "type": "base64", "data": d} for i, d in enumerate(images)]}


runpod.serverless.start({"handler": handler})
