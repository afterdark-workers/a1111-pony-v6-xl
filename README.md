# Pony Diffusion V6 XL — RunPod Serverless worker (AUTOMATIC1111)

A ready-to-build [RunPod Serverless](https://runpod.io?ref=qpguwapm) worker for **[Pony Diffusion V6 XL](https://civitai.com/models/257749?modelVersionId=290640)** by PurpleSmartAI, an SDXL finetune for anime, cartoon, furry and pony art, running on [AUTOMATIC1111 Stable Diffusion WebUI](https://github.com/AUTOMATIC1111/stable-diffusion-webui) v1.10.1 — the same settings as AUTOMATIC1111's own API: prompt weights like `(word:1.2)`, A1111 sampler names, clip skip. There is no web page: you use it from [Cobalt Pear](https://cobaltpear.github.io/) or any API call.

Models are baked into the image, so a cold start does not re-download anything.

> 18+ model. You download it with your own Civitai account and are responsible for following the model licenses.

## What's inside

| File | Source | Size |
|---|---|---|
| `models/Stable-diffusion/pony_diffusion_v6_xl.safetensors` | [Civitai 257749 / version 290640](https://civitai.com/models/257749?modelVersionId=290640) (fp16 pruned) | 6.8 GB |

Just the model as its creator released it — no LoRAs, no extensions, no upscalers. The VAE is built into the checkpoint. The file is checked by SHA-256 at build time. The webui runs API-only (no browser UI) with PyTorch for CUDA 12.8, so every RunPod GPU works.

## Setup (about 10 minutes + build time)

New to this? Follow the [step-by-step setup guide](https://cobaltpear.github.io/guide.html).

1. **Make your own private copy** — click **Use this template** → **Create a new repository** → choose **Private**.
   (Your Civitai token will be in it, so it must stay private.)
2. **Add your Civitai token** — get one at civitai.com → Account settings → Security & Apps → API Keys.
   In your copy, open `Dockerfile` → ✏️ edit → replace `PASTE_YOUR_CIVITAI_TOKEN_HERE` on line 6 → Commit.
   No RunPod account yet? [Sign up here](https://runpod.io?ref=qpguwapm) — a referral link: after you first add $10, RunPod gives you a bonus credit (usually $5–10) and this repo a small credit.
3. **Create the endpoint** — see [Create the endpoint](#create-the-endpoint) below.
4. **Create an API key** — RunPod → Settings → API Keys → **Restricted**, allow only this endpoint.

## Create the endpoint

RunPod → **Serverless** → **New Endpoint** → **Deploy from a GitHub repository** → pick your copy (the first time, **Edit connection** lets RunPod see it). Then, top to bottom on the page:

| Where on the page | What to set |
|---|---|
| **Endpoint name** | anything — your copy's name is fine |
| **GPU configuration** | tick a box of 16 GB or more (more boxes = easier to get a GPU) |
| **Max workers** | `1` |
| Click **Advanced settings** to open it: | |
| → **Active workers** | `0` — nothing to pay while idle |
| → **GPU count** | `1` |
| → **Idle timeout** | `5` sec |
| → **Enable FlashBoot** | on (the switch) · **Standard** |
| → **Enable execution timeout** | on · **Execution timeout** `600` sec |
| → click **Container configuration** to open it → **Container disk** | 30 GB |

Leave everything else as it is, then **Deploy** at the bottom. The first build takes about 20 minutes. The very first request after that waits another 3–10 minutes while a worker pulls the image; later cold starts are much faster.

## Updates

Your copy only holds the token. The build steps (`build.sh`, `handler.py`) are downloaded from this repo on every build, so when something changes upstream (a model file is replaced, a dependency breaks) it is fixed here — you just rebuild your endpoint.

To rebuild: commit any change to the `main` branch of your copy — RunPod builds again on every push to `main` (the endpoint's **Builds** tab shows it). Nothing to change? Edit `README.md` (✏️), add a line, **Commit changes…** → **Commit changes**.

### Model version

This repo always follows the version the model's creator currently recommends. Now: **V6 (start with this one), Civitai version 290640**.
Each change of the build files is kept as a release (`files-…`). To stay on one, replace `latest/download` with `download/files-…` (that release's name) in both `ADD` lines of your `Dockerfile`.

## Use it

The job `input` is passed to the webui's `/sdapi/v1/txt2img` as is, so any A1111 txt2img field works (`prompt`, `negative_prompt`, `seed`, `width`, `height`, `steps`, `cfg_scale`, `sampler_name`, `scheduler`, `batch_size`, `override_settings` …). `pack.json` in this repo holds the creator's settings and tells a client where the prompt, seed and size go (format `pack/1`, engine `json`).

Raw request:

```bash
curl -X POST https://api.runpod.ai/v2/<ENDPOINT_ID>/runsync \
  -H "Authorization: Bearer <API_KEY>" -H "Content-Type: application/json" \
  -d "{\"input\": $(jq '.input | .prompt = "score_9, score_8_up, score_7_up, score_6_up, score_5_up, score_4_up, source_anime, a girl reading a book in a cafe" | .seed = 1' pack.json)}"
```

The image comes back as base64 in `output.images[0].data` (the same shape as the ComfyUI worker).

Tips: 25 steps, CFG 7, Euler a, 1024 px, clip skip 2 — the creator's settings (clip skip 2 is in `pack.json` as `override_settings`; without it you get blobs). Start every prompt with the creator's template `score_9, score_8_up, score_7_up, score_6_up, score_5_up, score_4_up,` then describe what you want in plain words or tags. Optional tags: `source_anime`, `source_cartoon`, `source_furry`, `source_pony`, `rating_safe`, `rating_questionable`, `rating_explicit`. No negative prompt needed. SDXL sizes: about 1 megapixel, multiples of 64.

### Compatible clients

- [Cobalt Pear](https://cobaltpear.github.io/) — a one-page web app: add this repo's URL, your endpoint ID and API key, then just type a prompt. Everything stays in your browser. [Try the demo](https://cobaltpear.github.io/demo/) without RunPod.

Questions or ideas: [Discussions](https://github.com/cobaltpear/cobaltpear.github.io/discussions).
