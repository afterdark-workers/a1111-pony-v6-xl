#!/bin/sh
# Pony Diffusion V6 XL on AUTOMATIC1111 — everything the worker image needs. The Dockerfile in your copy downloads this file
# from the original repo on every build, so fixes made there reach you with a rebuild.
set -eu
case "${CIVITAI_TOKEN:-}" in ""|PASTE_*) echo "ERROR: set CIVITAI_TOKEN at the top of the Dockerfile" >&2; exit 1;; esac

# file <dest> <url> <sha256>
file() {
  wget -q -O "$1" "$2"
  echo "$3  $1" | sha256sum -c - || { echo "ERROR: $1 changed upstream — wait for an update of the original repo, then rebuild" >&2; exit 1; }
}

apt-get update -q && apt-get install -yq --no-install-recommends git wget ca-certificates libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*

# Stable Diffusion WebUI v1.10.1 (the last release) — CUDA 12.8 PyTorch so every RunPod GPU (Ampere to Blackwell) works
git clone -q --depth 1 --branch v1.10.1 https://github.com/AUTOMATIC1111/stable-diffusion-webui /webui
pip install -q --no-cache-dir torch==2.7.1+cu128 torchvision==0.22.1+cu128 --extra-index-url https://download.pytorch.org/whl/cu128
# CLIP's old setup.py needs pkg_resources — build it with an older setuptools, so the webui's installer finds it done
pip install -q --no-cache-dir "setuptools<70" wheel
pip install -q --no-cache-dir --no-build-isolation \
  https://github.com/openai/CLIP/archive/d50d76daa670286dd6cacf3bcd80b5e4823fc8e1.zip \
  https://github.com/mlfoundations/open_clip/archive/bb6e834e9c70d9c27d0dc3ecedeebeaeb1ffad6b.zip
# the webui's own installer, without a GPU. Stability-AI/stablediffusion was taken down — the same code from a mirror
cd /webui
STABLE_DIFFUSION_REPO=https://github.com/w-e-w/stablediffusion.git \
  python launch.py --skip-torch-cuda-test --exit
# the handler gets its own Python: today's runpod wants newer packages than the webui's (installing both in one
# Python left pip searching for hours)
python -m venv /rp && /rp/bin/pip install -q --no-cache-dir runpod requests
# the SDXL text encoder's tokenizer, so a cold start downloads nothing
HF_HOME=/hf python -c "from transformers import CLIPTokenizer; CLIPTokenizer.from_pretrained('openai/clip-vit-large-patch14')"
rm -rf /root/.cache/pip

# Pony Diffusion V6 XL — SDXL checkpoint, fp16 pruned, VAE built in (Civitai model 257749 / version 290640, 6.8GB)
file /webui/models/Stable-diffusion/pony_diffusion_v6_xl.safetensors \
  "https://civitai.com/api/download/models/290640?type=Model&format=SafeTensor&size=pruned&fp=fp16&token=${CIVITAI_TOKEN}" \
  67ab2fd8ec439a89b3fedb15cc65f54336af163c7eb5e4f2acc98f090a29b0b3
