"""This worker on Modal (modal.com) instead of RunPod — the same Dockerfile, build and handler, the same requests.

It answers like a RunPod endpoint: POST <url>/run {"input": …} → {"id"} · GET <url>/status/<id> · POST <url>/cancel/<id>,
with the header «Authorization: Bearer <your password>». Setup: README.md → «Or run it on Modal».
"""
import json, os, subprocess, time, urllib.error, urllib.request
from pathlib import Path
import modal

GPU = "A10"  # 24 GB — others: "L4" (24 GB), "L40S" (48 GB), "A100-80GB", "H100" — prices: modal.com/pricing
HERE = Path(__file__).parent
LOCAL = "http://127.0.0.1:8000"

app = modal.App(HERE.name)  # your folder's name — the worker's URL starts with it
# Modal runs on a Python of its own (3.12, put over the image's «python»); the webui and the handler keep the image's 3.10
image = modal.Image.from_dockerfile(HERE / "Dockerfile", context_dir=HERE, add_python="3.12").run_commands(
    "ln -sf /usr/local/bin/python3.10 /rp/bin/python",
    """sed -i 's|"/usr/local/bin/python", "launch.py"|"/usr/local/bin/python3.10", "launch.py"|' /handler.py""",
    "grep -q 'python3.10\", \"launch.py' /handler.py && /rp/bin/python -c 'import runpod'",
)
key = modal.Secret.from_name("cobaltpear-key")


@app.cls(image=image, gpu=GPU, secrets=[key], scaledown_window=60, timeout=1800)
class Worker:
    @modal.enter()
    def start(self):
        # the worker's own handler.py (it starts the webui and moves to its own Python), answering on a local port
        # instead of RunPod's queue — RunPod's test API, /runsync
        self.p = subprocess.Popen(["/rp/bin/python", "-u", "/handler.py", "--rp_serve_api", "--rp_api_host", "127.0.0.1", "--rp_api_port", "8000"])
        while True:
            if self.p.poll() is not None:
                raise RuntimeError(f"handler.py stopped (exit {self.p.returncode}) — see the log above")
            try:
                urllib.request.urlopen(LOCAL + "/docs", timeout=5)
                return
            except (urllib.error.URLError, OSError):
                time.sleep(0.5)

    @modal.method()
    def run(self, job: dict) -> dict:
        req = urllib.request.Request(LOCAL + "/runsync", data=json.dumps({"input": job.get("input") or {}}).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=1800) as r:
            res = json.loads(r.read())
        return res.get("output") if res.get("status") == "COMPLETED" else {"error": str(res.get("error") or res)[:1000]}


@app.function(image=modal.Image.debian_slim().pip_install("fastapi[standard]"), secrets=[key])
@modal.asgi_app()
def api():
    import hmac
    from fastapi import FastAPI, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse
    web, want = FastAPI(), "Bearer " + os.environ["CP_KEY"]

    @web.middleware("http")
    async def need_key(request: Request, call_next):  # a browser's preflight (OPTIONS) carries no key — CORS answers it
        if request.method != "OPTIONS" and not hmac.compare_digest(request.headers.get("authorization", ""), want):
            return JSONResponse({"error": "Wrong key"}, status_code=401)
        return await call_next(request)
    web.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])  # added last = runs first

    @web.post("/run")
    def run(job: dict):
        return {"id": Worker().run.spawn(job).object_id, "status": "IN_QUEUE"}

    @web.get("/status/{call_id}")
    def status(call_id: str):
        try:
            out = modal.FunctionCall.from_id(call_id).get(timeout=0)
        except TimeoutError:
            return {"id": call_id, "status": "IN_PROGRESS"}
        except Exception as e:
            return {"id": call_id, "status": "FAILED", "error": str(e)[:300]}
        if isinstance(out, dict) and out.get("error") and not out.get("images"):
            return {"id": call_id, "status": "FAILED", "error": out["error"], "output": out}
        return {"id": call_id, "status": "COMPLETED", "output": out}

    @web.post("/cancel/{call_id}")
    def cancel(call_id: str):
        modal.FunctionCall.from_id(call_id).cancel()
        return {"id": call_id, "status": "CANCELLED"}

    return web
