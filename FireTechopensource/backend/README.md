# Bug Buster backend

Local-only backend for **Bug Buster - Visual Bug-to-Patch Engine**. It looks at a screenshot of a broken page,
scans your local repository, asks **local Gemma (via Ollama)** what is wrong, and returns a suggested Git diff
for a human to review. It never edits your files and never calls any cloud AI.

## Files

| File | Purpose |
|---|---|
| `main.py` | FastAPI app: `/health` and `/analyze-bug`, settings, CORS, upload checks, error handling. |
| `scanner.py` | Safe repository scanner, ASCII tree, keyword-based file selection, numbered code for the model. |
| `gemma_engine.py` | Ollama calls: stage 1 (read the screenshot), stage 2 (find the culprit, write JSON), JSON repair/validation. |
| `patch_validator.py` | Checks the suggested diff is safe and well-formed, fixes wrong line numbers, never applies anything. |
| `requirements.txt` | Python packages. |
| `.env.example` | Settings template. Copy to `.env`. |

## Setup - Windows PowerShell

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1        # if blocked: Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
pip install -r requirements.txt
copy .env.example .env

# Start Ollama (skip if the Ollama app is already running in the system tray)
ollama serve                         # leave this window open, use a NEW PowerShell window for the rest
ollama pull gemma3:4b

# Back in the backend folder, with the venv activated:
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

## Setup - Linux / macOS

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

ollama serve &                       # skip if Ollama is already running
ollama pull gemma3:4b

uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

`127.0.0.1` keeps the API reachable only from your own computer. That matters because the API reads folders you
name. Use `--host 0.0.0.0` only if another device must reach it, and then set `ALLOWED_REPO_ROOTS` in `.env`.

## Test it

1. Health: open http://localhost:8000/health (expect `"status": "ok"` and `"model_available": true`).
2. Interactive docs: http://localhost:8000/docs (try `/analyze-bug` in the browser).
3. Command line (Linux/macOS):
   ```bash
   curl -X POST http://localhost:8000/analyze-bug \
     -F "image=@screenshot.png" \
     -F "repo_path=/full/path/to/demo-repo" \
     -F "issue_hint=The Log in button text is invisible"
   ```
   Windows PowerShell (use `curl.exe`; plain `curl` is a different command there):
   ```powershell
   curl.exe -X POST http://localhost:8000/analyze-bug `
     -F "image=@C:\full\path\bug.png" `
     -F "repo_path=C:\full\path\to\demo-repo" `
     -F "issue_hint=The Log in button text is invisible"
   ```

The included `demo-repo/` has one deliberate bug: the login button's text colour equals its background colour.
Open `demo-repo/index.html` in a browser, take a screenshot, and use that.

## Response

```json
{
  "culprit_file": "styles.css",
  "root_cause": "Two beginner-friendly sentences.",
  "git_diff": "diff --git a/styles.css b/styles.css\n--- a/styles.css\n+++ b/styles.css\n@@ ... @@\n...",
  "fixed_code": "corrected snippet",
  "analysis": { "confidence": "confirmed", "evidence": [], "guesses": [], "patch_verified": true, "...": "..." }
}
```

The frontend only needs the four top-level fields. `analysis` is extra detail (confidence, evidence vs guesses,
which files were read, patch warnings) that the UI may show or ignore. If the evidence is not enough, the backend
returns `culprit_file: "Unknown - insufficient evidence"` with empty `git_diff` / `fixed_code` instead of guessing.

To apply a patch after reviewing it: save `git_diff` to `fix.patch`, run `git apply --check fix.patch`, then `git apply fix.patch`.

## Errors

All errors are JSON: `{"detail": "what went wrong", "error": "code"}`.
400 bad path, 403 folder not allowed, 413 upload too large, 415 not a PNG/JPEG/WebP, 422 no source files,
503 Ollama down or model missing, 504 timeout, 502 model gave unusable output.

## Troubleshooting

* **Browser says CORS error**: add your frontend's exact address to `ALLOWED_ORIGINS` in `.env` and restart. Opening
  `index.html` by double-clicking (`file://`) will not work; serve it (VS Code Live Server, or `python -m http.server 8080`).
* **`model_available: false`**: run `ollama pull gemma3:4b` (or set `OLLAMA_MODEL` to a model you have). The model must
  support images; `gemma3:4b` does, `gemma3:1b` does not.
* **Slow or timeouts**: lower `OLLAMA_NUM_CTX` to 8192 and `MAX_PROMPT_SOURCE_KB` to 20; use a smaller screenshot.
* **Why two source limits?** `MAX_TOTAL_SOURCE_KB` caps what the scanner reads; `MAX_PROMPT_SOURCE_KB` caps what is
  sent to Gemma. A 4B model works best with a few small files, so the second one is much lower.
