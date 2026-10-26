"""RunPod Serverless handler for AUTOMATIC1111 Stable Diffusion WebUI.

The webui runs API-only on 127.0.0.1:7860 inside the worker. A job's `input` is sent to /sdapi/v1/txt2img as is
(prompt, negative_prompt, seed, width, height, steps, cfg_scale, sampler_name, scheduler, override_settings …),
and the pictures come back like the ComfyUI worker's: output.images = [{filename, type: "base64", data}].
Extra LoRAs: input.remote_loras = [{name, url, sha256, strength}] (at most REMOTE_LORA_MAX, default 4) — downloaded once
into models/Lora and added to the prompt as <lora:name:strength>; a LoRA that doesn't look made for SDXL comes back as
output.warning. LoRAs in the Dockerfile's LORAS line are built in: input.baked_loras picks which ones a picture uses
(see pick_baked), and output.built_in lists them all.
"""
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse

# run in the handler's own Python (see build.sh); the webui keeps the image's Python
if sys.prefix != "/rp":
    os.execv("/rp/bin/python", ["/rp/bin/python", "-u", __file__, *sys.argv[1:]])

import requests
import runpod

API = "http://127.0.0.1:7860"
CKPT = sorted(glob.glob("/webui/models/Stable-diffusion/*.safetensors"))[0]

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


LORA_DIR = "/webui/models/Lora"
REMOTE_LORA_MAX = int(os.environ.get("REMOTE_LORA_MAX", 4))
REMOTE_LORA_KEEP = int(os.environ.get("REMOTE_LORA_KEEP", max(4, REMOTE_LORA_MAX)))
REMOTE_LORA_NAME = re.compile(r"remote_[A-Za-z0-9_-]{1,80}\.safetensors")
# tensor names only an SDXL LoRA has (kohya and diffusers style); Flux-style blocks mean it was made for another model
SDXL_KEY = re.compile(r"lora_te[12]_|text_encoder_2|(input|output)_blocks|middle_block|unet.*transformer_blocks[._][1-9]")
OTHER_KEY = re.compile(r"(double|single)_blocks|single_transformer_blocks")


def lora_keys(path):
    """Tensor names from the safetensors header (no tensors are read)."""
    with open(path, "rb") as f:
        n = int.from_bytes(f.read(8), "little")
        return [k for k in json.loads(f.read(n)) if k != "__metadata__"]


def fetch_remote_loras(items):
    """Download missing LoRAs only. Returns (error, names of LoRAs that don't look made for SDXL)."""
    if not isinstance(items, list):
        return "'remote_loras' must be a list", []
    if items and REMOTE_LORA_MAX == 0:
        return "this worker takes only LoRAs built into it (REMOTE_LORA_MAX is 0)", []
    if len(items) > REMOTE_LORA_MAX:
        return (f"this worker takes at most {REMOTE_LORA_MAX} LoRAs per picture — for more, set REMOTE_LORA_MAX "
                "in the endpoint's environment variables (RunPod → your endpoint → Manage → Edit Endpoint)"), []
    os.makedirs(LORA_DIR, exist_ok=True)
    odd = []
    for it in items:
        name, url, digest = (it or {}).get("name"), (it or {}).get("url"), (it or {}).get("sha256")
        if not (isinstance(name, str) and REMOTE_LORA_NAME.fullmatch(name) and isinstance(url, str)
                and url.startswith("https://") and isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest)):
            return f"invalid remote_loras entry: {name!r}", []
        dest = os.path.join(LORA_DIR, name)
        if os.path.exists(dest):
            os.utime(dest)  # mark as recently used so cleanup keeps it
        else:
            print(f"worker-a1111 - Downloading remote LoRA {name}")
            t0, tmp, h = time.time(), dest + ".part", hashlib.sha256()
            try:
                with requests.get(url, stream=True, timeout=(10, 120)) as r:
                    r.raise_for_status()
                    with open(tmp, "wb") as f:
                        for chunk in r.iter_content(1 << 20):
                            h.update(chunk)
                            f.write(chunk)
            except Exception as e:
                if os.path.exists(tmp):
                    os.remove(tmp)
                return f"remote LoRA {name} download failed: {e}", []
            if h.hexdigest() != digest:
                os.remove(tmp)
                return f"remote LoRA {name} sha256 mismatch", []
            os.replace(tmp, dest)
            print(f"worker-a1111 - Remote LoRA {name} ready ({os.path.getsize(dest) >> 20} MB, {time.time() - t0:.1f}s)")
        keys = lora_keys(dest)
        if any(OTHER_KEY.search(k) for k in keys) or not any(SDXL_KEY.search(k) for k in keys):
            odd.append(name)
    remote = sorted((os.path.join(LORA_DIR, f) for f in os.listdir(LORA_DIR)
                     if f.startswith("remote_") and f.endswith(".safetensors")), key=os.path.getmtime)
    for old in remote[:-REMOTE_LORA_KEEP]:
        os.remove(old)
    return None, odd


# LoRAs built into the worker — the Dockerfile's LORAS line ("<Civitai or Hugging Face link> [strength] …") is downloaded
# at build time by `handler.py --bake-loras`. A request picks which ones it uses (input.baked_loras, see pick_baked);
# without that every one is used, before the request's own LoRAs.
BAKED_LIST = "/baked_loras.json"
NUMBER = re.compile(r"-?\d+(\.\d+)?")


def setting(key):
    """A build setting: the Dockerfile line, or civitai.env in the copy (Cobalt Pear's «Add your token» link writes it)."""
    v = os.environ.get(key, "")
    if (not v or v.startswith("PASTE_")) and os.path.exists("/setup/civitai.env"):
        for line in open("/setup/civitai.env"):
            k, _, x = line.partition("=")
            if k.strip() == key:
                v = x.strip().strip("\"'")
    return "" if v.startswith("PASTE_") else v


def lora_source(link):
    """(download URL, sha256 or None, request headers) for a Civitai or Hugging Face LoRA link."""
    u = urllib.parse.urlparse(link)
    host, q = u.hostname or "", urllib.parse.parse_qs(u.query)
    if host == "civitai.com" or host.endswith(".civitai.com"):
        m = re.search(r"/api/download/models/(\d+)", u.path)
        version = m.group(1) if m else (q.get("modelVersionId") or [None])[0]
        if not version:
            m = re.search(r"/models/(\d+)", u.path)
            if not m:
                raise ValueError(f"{link}: not a Civitai model link")
            version = requests.get(f"https://civitai.com/api/v1/models/{m.group(1)}", timeout=30).json()["modelVersions"][0]["id"]
        v = requests.get(f"https://civitai.com/api/v1/model-versions/{version}", timeout=30).json()
        f = next((f for f in v["files"] if f.get("primary")), v["files"][0])
        token = setting("CIVITAI_TOKEN")
        url = f["downloadUrl"]
        if token:
            url += ("&" if "?" in url else "?") + "token=" + token
        return url, (f.get("hashes") or {}).get("SHA256", "").lower() or None, {}
    if host == "huggingface.co":
        hdr = {"Authorization": "Bearer " + setting("HF_TOKEN")} if setting("HF_TOKEN") else {}
        p = u.path.strip("/").split("/")
        if len(p) > 4 and p[2] in ("blob", "resolve"):
            return f"https://huggingface.co/{p[0]}/{p[1]}/resolve/{'/'.join(p[3:])}", None, hdr
        if len(p) < 2:
            raise ValueError(f"{link}: not a Hugging Face model link")
        tree = requests.get(f"https://huggingface.co/api/models/{p[0]}/{p[1]}/tree/main?recursive=1", headers=hdr, timeout=30).json()
        files = [x["path"] for x in tree if x.get("type") == "file" and x["path"].endswith(".safetensors")]
        if len(files) != 1:
            raise ValueError(f"{link}: {len(files)} .safetensors files in that repo — link the one you want")
        return f"https://huggingface.co/{p[0]}/{p[1]}/resolve/main/{files[0]}", None, hdr
    raise ValueError(f"{link}: not a Civitai or Hugging Face link")


def bake_loras(spec, lora_dir, after=None):
    """Download the LORAS line's LoRAs as baked_<n>.safetensors and list them in BAKED_LIST."""
    items = []
    for w in spec.split():
        if NUMBER.fullmatch(w) and items:
            items[-1]["strength"] = float(w)
        else:
            items.append({"link": w, "strength": 1.0})
    os.makedirs(lora_dir, exist_ok=True)
    for i, it in enumerate(items):
        url, digest, hdr = lora_source(it["link"])
        it["name"] = f"baked_{i}.safetensors"
        dest, h = os.path.join(lora_dir, it["name"]), hashlib.sha256()
        with requests.get(url, headers=hdr, stream=True, timeout=(10, 300)) as r:
            if r.status_code in (401, 403):
                raise ValueError(f"{it['link']}: download refused ({r.status_code}) — a Civitai LoRA needs CIVITAI_TOKEN, a gated HF one HF_TOKEN")
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    h.update(chunk)
                    f.write(chunk)
        if digest and h.hexdigest() != digest:
            raise ValueError(f"{it['link']}: sha256 mismatch")
        it["sha256"] = h.hexdigest()
        if after:
            after(dest)
        print(f"LoRA {i + 1}/{len(items)} built in: {it['link']} × {it['strength']:g} ({os.path.getsize(dest) >> 20} MB)")
    with open(BAKED_LIST, "w") as f:
        json.dump(items, f)


def baked_loras():
    try:
        with open(BAKED_LIST) as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def pick_baked(baked, chosen):
    """input.baked_loras = [{"link", "strength"}] picks the built-in LoRAs for this picture ([] = none);
    without it every built-in LoRA is used at its LORAS strength. One that isn't built in (yet) is left out
    and named in the warning, so a picture sent while the worker builds again still comes out.
    Returns (LoRAs, links left out, error)."""
    if chosen is None:
        return baked, [], None
    if not isinstance(chosen, list):
        return [], [], "'baked_loras' must be a list"
    out, missing = [], []
    for c in chosen:
        link = str((c or {}).get("link", "")).rstrip("/") if isinstance(c, dict) else ""
        b = next((b for b in baked if b["link"].rstrip("/") == link), None)
        if not b:
            missing.append(link or str(c))
            continue
        try:
            out.append({**b, "strength": float(c.get("strength", b["strength"]))})
        except (TypeError, ValueError):
            return [], [], f"invalid strength for LoRA {link}"
    return out, missing, None


def not_built(missing):
    return (f"{len(missing)} LoRA is not built into this worker yet — the picture was made without it "
            "(the worker is still building, or it is not on the LORAS line): " + ", ".join(missing))


if "--bake-loras" in sys.argv:  # Dockerfile, at build time
    bake_loras(setting("LORAS"), LORA_DIR)
    sys.exit(0)
BAKED = baked_loras()

webui = subprocess.Popen(
    ["/usr/local/bin/python", "launch.py", "--skip-prepare-environment", "--skip-install", "--skip-version-check",
     "--nowebui", "--api", "--port", "7860", "--no-download-sd-model", "--no-hashing",
     "--opt-sdp-attention", "--no-half-vae", "--ckpt", CKPT],
    cwd="/webui", env={**os.environ, "HF_HOME": "/hf"},
)



def handler(job):
    inp = dict(job.get("input") or {})
    if not inp.get("prompt"):
        return {"error": "input.prompt is required"}
    loras, odd = inp.pop("remote_loras", None) or [], []
    baked, not_baked, err = pick_baked(BAKED, inp.pop("baked_loras", None))
    if err:
        return {"error": err}
    if loras:
        err, odd = fetch_remote_loras(loras)
        if err:
            return {"error": err}
    inp.update(save_images=False, send_images=True)
    wait_ready()
    if loras:
        requests.post(API + "/sdapi/v1/refresh-loras", timeout=60)  # the webui lists LoRA files once; new ones need this
    inp["prompt"] += "".join(f" <lora:{l['name'][:-12]}:{float(l.get('strength', 1)):g}>" for l in baked + loras)
    r = requests.post(API + "/sdapi/v1/txt2img", json=inp, timeout=900)
    if not r.ok:
        return {"error": f"txt2img {r.status_code}: {r.text[:500]}"}
    images = r.json().get("images") or []
    out = {"images": [{"filename": f"{job['id']}_{i}.png", "type": "base64", "data": d} for i, d in enumerate(images)]}
    warnings = [odd and f"{', '.join(odd)} doesn't look made for an SDXL model — it may do nothing", not_baked and not_built(not_baked)]
    if any(warnings):
        out["warning"] = " · ".join(filter(None, warnings))
    out["built_in"] = [b["link"] for b in BAKED]  # the app learns which LoRAs this worker has
    return out


runpod.serverless.start({"handler": handler})
