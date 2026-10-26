# Pony Diffusion V6 XL — RunPod Serverless worker on AUTOMATIC1111 Stable Diffusion WebUI
# Build on RunPod from your own PRIVATE copy of this repo (Dockerfile path = Dockerfile, build context = .).
# The build steps are downloaded from the original repo, so you never need to edit anything but the token (and the optional LORAS line).

# >>> Put your Civitai API token here (civitai.com → Account settings → Security & Apps → API Keys). Keep your repo PRIVATE. <<<
ARG CIVITAI_TOKEN=PASTE_YOUR_CIVITAI_TOKEN_HERE

# >>> Optional — LoRAs built into the worker (each picture picks which to use): Civitai or Hugging Face links, each followed by
#     its strength (1 when left out), separated by spaces. Leave it empty for none. Example:
#     ARG LORAS="https://civitai.com/models/12345 0.8 https://huggingface.co/user/some-lora 0.6"   <<<
ARG LORAS=""

FROM python:3.10-slim-bookworm
ARG LORAS
ARG CIVITAI_TOKEN
ADD https://github.com/afterdark-workers/a1111-pony-v6-xl/releases/latest/download/build.sh /build.sh
RUN CIVITAI_TOKEN="$CIVITAI_TOKEN" sh /build.sh
ADD https://github.com/afterdark-workers/a1111-pony-v6-xl/releases/latest/download/handler.py /handler.py
RUN python /handler.py --bake-loras
CMD ["python", "-u", "/handler.py"]
