# Lumix 4K Image Enhancer — Backend API

FastAPI backend service powering AI super-resolution (Real-ESRGAN) and high-fidelity 4K image upscaling with asynchronous background job handling and automated temporary file cleanup.

---

## 🛠️ Prerequisites

- **Python 3.10+** (Python 3.11, 3.12, or 3.13 supported)
- **pip** package manager

---

## 📦 Installation & Setup

### 1. Navigate to the backend directory (or repository root)

```bash
cd backend
```

### 2. Create and activate a virtual environment (recommended)

**Windows (PowerShell / Command Prompt):**
```powershell
python -m venv venv
.\venv\Scripts\activate
```

**macOS / Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install core dependencies

```bash
pip install -r requirements.txt
```

### 4. (Optional) Install PyTorch for AI Super-Resolution (Real-ESRGAN)

The backend features an intelligent dual-engine architecture:
- **Real-ESRGAN AI Super-Resolution**: Requires PyTorch. Uses deep residual dense networks with chunked 256×256 tiled inference for low memory consumption (~100MB RAM).
- **High-Fidelity Lanczos HQ Fallback**: Automatically active if PyTorch is not installed. Uses 8-tap Lanczos resampling + Unsharp Mask edge sharpening (completes in ~1 second).

To enable the Real-ESRGAN AI engine:

**CPU (Lightweight, cross-platform):**
```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
```

**GPU (NVIDIA CUDA support):**
```bash
pip install torch --index-url https://download.pytorch.org/whl/cu121
```

> **Note:** The Real-ESRGAN weights (`RealESRGAN_x4plus.pth`, ~64MB) are automatically downloaded from GitHub releases to `backend/weights/` upon first use if not already present.

---

## 🚀 Running the Server Locally

### Option A: Running from repository root
```bash
uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

### Option B: Running directly from the `backend/` directory
```bash
cd backend
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

* **API Base URL**: `http://127.0.0.1:8000`
* **Interactive Swagger UI**: `http://127.0.0.1:8000/docs`
* **ReDoc Documentation**: `http://127.0.0.1:8000/redoc`

---

## ⚙️ Environment Variables (Optional)

You can set these environment variables in your terminal or `.env` file:

| Variable | Default | Description |
| :--- | :--- | :--- |
| `PORT` | `8000` | Port for the Uvicorn server to bind to. |
| `ALLOWED_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000,...` | Comma-separated list of allowed CORS origins. |

---

## 📡 Key API Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/health` | Service health check (`{"status": "ok", "service": "image-4k-upscaler-api"}`). |
| `POST` | `/enhance?engine=auto` | Upload an image (`multipart/form-data` with `file`) and queue async enhancement. Returns `job_id`. |
| `GET` | `/status/{job_id}` | Poll background progress percentage, stage message, and result metadata. |
| `GET` | `/preview/{job_id}` | Stream enhanced image directly for in-browser before/after comparison. |
| `GET` | `/download/{job_id}` | Download enhanced image with formatted filename (`<original-name>-4k.<ext>`). |

---

## 🧹 Automated Temporary File Cleanup

The backend includes an automatic cleanup lifespan routine (`cleanup_old_jobs()`):
- Runs immediately on server startup and hourly via a background loop.
- Automatically purges upload inputs, generated 4K outputs, and job metadata from `backend/temp/` that are older than **1 hour** (`JOB_TTL_SECONDS = 3600`).
