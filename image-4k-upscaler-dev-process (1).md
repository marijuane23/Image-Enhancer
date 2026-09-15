# Development Process: Image 4K Enhancer Website

A step-by-step plan for building a web app that takes a user-uploaded image and upscales/enhances it to 4K resolution.

---

## 1. Project Overview

**Goal:** Let a user upload an image, run it through an upscaling/enhancement pipeline, and download the result at 4K (3840×2160) or proportionally scaled resolution.

**Core value proposition:**
- Simple drag-and-drop upload
- Fast turnaround (or clear progress feedback for slower AI models)
- Noticeable quality improvement (sharper edges, reduced noise/artifacts, larger dimensions)

**Out of scope (v1):** batch processing, video upscaling, user accounts/billing — these can be phase 2+.

---

## 2. Tech Stack Decision

**Decided stack (v1):**

| Layer | Choice |
|---|---|
| Frontend | HTML/CSS/JS (static) |
| Frontend hosting | **GitHub Pages** |
| Backend | FastAPI (Python) |
| Backend hosting | **Render** (Web Service) |
| Upscaling engine | Real-ESRGAN (AI super-resolution) |
| Storage | Temp local disk on Render instance, auto-delete after download |

**Important constraint — no GPU on Render:** Render doesn't offer GPU instances, so Real-ESRGAN will run on CPU only. Expect several seconds up to ~30-60s per image (vs. near-instant on a GPU), depending on image size and Render instance tier. This makes async job handling (Phase 4) important rather than optional — don't make the user wait on a blocking request. The free tier also has cold starts (the service spins down after inactivity), so the first request after idle time will be slow; a paid instance avoids this if responsiveness matters.

---

## 3. Architecture

```
[Browser]
   |  (upload image, drag-drop or file picker)
   v
[Frontend: HTML/CSS/JS — hosted on GitHub Pages]
   |  POST https://your-app.onrender.com/enhance (multipart/form-data)
   |  (cross-origin request — requires CORS config on backend)
   v
[FastAPI Backend — hosted on Render]
   |  1. Validate file (type, size, dimensions)
   |  2. Save to temp storage
   |  3. Queue/run upscaling job (async — CPU-only inference is slow)
   v
[Upscaling Engine: Real-ESRGAN, CPU inference]
   |  Runs inference, outputs upscaled image
   v
[FastAPI Backend]
   |  Return result (file URL or base64)
   v
[Frontend on GitHub Pages]
   |  Show before/after preview + download button
```

**Two separate deployments, two separate domains:**
- Frontend: `https://<your-username>.github.io/<repo-name>/`
- Backend: `https://<your-app-name>.onrender.com`

---

## 4. Development Phases

### Phase 1 — Setup & Scaffolding
- [x] Decide one repo with `/frontend` + `/backend` folders, or two separate repos (simpler for Render + GitHub Pages, since each deploys independently)
- [x] Set up FastAPI project with a basic `/health` endpoint
- [x] Set up frontend shell (upload form, placeholder preview area)
- [x] Decide local dev workflow (run backend locally, frontend via live-server, pointing frontend at `http://localhost:8000` during dev)

### Phase 2 — Core Upload Flow
- [x] Build drag-and-drop + file picker upload UI
- [x] Client-side validation (file type: jpg/png/webp; max size, e.g. 10MB)
- [x] `POST /enhance` endpoint accepting multipart file upload
- [x] Save uploaded file to a temp directory with a unique ID (UUID)

### Phase 3 — Upscaling Engine Integration
- [x] Install and test Real-ESRGAN locally (or chosen model) on sample images
- [x] Wrap inference in a Python function: `enhance_image(input_path) -> output_path`
- [x] Handle target resolution logic (scale factor vs fixed 3840×2160, preserve aspect ratio)
- [x] Add error handling (corrupt file, unsupported format, model failure)

### Phase 4 — Async Job Handling ✅ COMPLETE
- [x] Decided on async job queue using FastAPI `BackgroundTasks` (no external broker needed for v1)
- [x] Added `GET /status/{job_id}` polling endpoint with progress %, status, and progress_message fields
- [x] `GET /download/{job_id}` and `GET /preview/{job_id}` endpoints for result delivery
- [x] Persistent job metadata stored in `temp/{job_id}_meta.json` (survives across requests)
- [x] Frontend: `pollJobStatus()` polls every 2s, live progress bar with percentage, status badge (Queued / Processing / Completed / Failed)
- [x] Download button revealed on completion; result stats panel shows engine, output dimensions, processing time
- [x] Spinner animation on Enhance button while uploading/processing

### Phase 5 — Result Delivery ✅ COMPLETE
- [x] Stream/serve enhanced image via `GET /preview/{job_id}` for fast in-browser preview and comparison
- [x] Frontend: interactive before/after comparison slider with mouse drag, touch swipe, click-to-reposition, and keyboard arrow controls
- [x] Download endpoint `GET /download/{job_id}` with ASCII-sanitized `Content-Disposition: attachment; filename="<original_name>-4k.<ext>"`
- [x] Auto-cleanup utility: `cleanup_old_jobs()` automatically deletes temporary input/output files and metadata older than 1 hour (JOB_TTL_SECONDS = 3600)
- [x] FastAPI lifespan manager runs startup cleanup and triggers background hourly cleanup loops without blocking requests

### Phase 6 — Deployment
- [ ] Push backend repo (or `/backend` folder) to GitHub, connect it to Render as a new Web Service
- [ ] Set Render build command (e.g. `pip install -r requirements.txt`) and start command (e.g. `uvicorn main:app --host 0.0.0.0 --port $PORT`)
- [ ] Choose Render instance tier — free tier for testing (expect cold starts), paid tier if you need it always warm/responsive
- [ ] Push frontend repo (or `/frontend` folder) to GitHub, enable GitHub Pages in repo settings
- [ ] Point frontend's `fetch()` calls to the live Render backend URL (`https://your-app.onrender.com`)
- [ ] Configure CORS in FastAPI (`fastapi.middleware.cors`) to explicitly allow your GitHub Pages origin
- [ ] Set upload size limits at the FastAPI level (Render's own request limits apply too — check current plan limits)
- [ ] Test the full cross-origin flow end-to-end (not just locally) — CORS issues only show up once both are actually deployed on separate domains

### Phase 7 — Polish & Hardening
- [ ] Rate limiting (prevent abuse of the inference endpoint)
- [ ] Progress indicator / estimated time messaging
- [ ] Mobile-responsive UI
- [ ] Basic analytics (optional): track number of enhancements run
- [ ] Error states: file too large, unsupported format, server overloaded

---

## 5. Key Technical Decisions to Make Early

1. **Which upscaling method?**
   - Simple/fast: bicubic interpolation + sharpening (low quality, instant)
   - AI-based: Real-ESRGAN / GFPGAN (much better quality, needs GPU for reasonable speed)
2. **Sync vs async processing** — AI upscaling can take several seconds to a minute per image; async with a job ID avoids request timeouts.
3. **Where does inference run?** — locally self-hosted (your Ollama/Cloudflare Tunnel pattern), or a rented GPU instance.
4. **File lifecycle** — how long do you keep uploaded/generated images before deleting them (privacy + storage cost).

---

## 6. Suggested Folder Structure

Since GitHub Pages and Render each deploy from their own source, either keep both folders in one repo (deploy each subfolder separately) or split into two repos — two repos is simpler to reason about with Render's auto-deploy-on-push:

```
image-4k-enhancer/
├── backend/                 # → deployed to Render
│   ├── main.py              # FastAPI app entrypoint (incl. CORS config)
│   ├── routes/
│   │   └── enhance.py
│   ├── services/
│   │   └── upscaler.py      # Real-ESRGAN wrapper
│   ├── temp/                # uploaded + processed files (gitignored)
│   └── requirements.txt
├── frontend/                # → deployed to GitHub Pages
│   ├── index.html
│   ├── style.css
│   └── app.js                # fetch() calls point to Render backend URL
└── README.md
```

---

## 7. Milestones Checklist (Condensed)

- [x] M1: Upload + preview working (no enhancement yet)
- [x] M2: Basic upscaling working end-to-end (even with a crude method)
- [x] M3: AI model (Real-ESRGAN) integrated and producing good results
- [x] M4: Async job handling + progress feedback
- [ ] M5: Deployed and publicly accessible
- [ ] M6: Polish, error handling, rate limiting
