# Pony Diffusion V6 XL — RunPod Serverless worker on AUTOMATIC1111 Stable Diffusion WebUI
# Build on RunPod from your own PRIVATE copy of this repo (Dockerfile path = Dockerfile, build context = .).
# The build steps are downloaded from the original repo, so you never need to edit anything but the token.

# >>> Put your Civitai API token here (civitai.com → Account settings → Security & Apps → API Keys). Keep your repo PRIVATE. <<<
ARG CIVITAI_TOKEN=PASTE_YOUR_CIVITAI_TOKEN_HERE

FROM python:3.10-slim-bookworm
ARG CIVITAI_TOKEN
ADD https://github.com/afterdark-workers/a1111-pony-v6-xl/releases/latest/download/build.sh /build.sh
RUN CIVITAI_TOKEN="$CIVITAI_TOKEN" sh /build.sh
ADD https://github.com/afterdark-workers/a1111-pony-v6-xl/releases/latest/download/handler.py /handler.py
CMD ["python", "-u", "/handler.py"]
