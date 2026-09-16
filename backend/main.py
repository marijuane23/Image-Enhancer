import os
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


# ── Phase 5: Periodic auto-cleanup lifespan ───────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup: run an immediate cleanup pass, then schedule hourly cleanups.
    Shutdown: cancel the cleanup task gracefully.
    """
    from routes.enhance import cleanup_old_jobs

    async def _cleanup_loop():
        while True:
            try:
                cleanup_old_jobs()
            except Exception as exc:
                print(f"[cleanup] Error during periodic cleanup: {exc}")
            await asyncio.sleep(3600)  # run every hour

    async def _prewarm_weights():
        try:
            from services.upscaler import ensure_weights_available
            await asyncio.to_thread(ensure_weights_available)
        except Exception as exc:
            print(f"[prewarm] Note: {exc}")

    cleanup_task = asyncio.create_task(_cleanup_loop())
    prewarm_task = asyncio.create_task(_prewarm_weights())
    yield
    cleanup_task.cancel()
    prewarm_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="Image 4K Upscaler API",
    description="Backend API for AI-powered 4K Image Super-Resolution and Enhancement",
    version="1.0.0",
    lifespan=lifespan
)

# Configure CORS for local development and GitHub Pages deployments
allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "")
allowed_origins = [origin.strip() for origin in allowed_origins_env.split(",") if origin.strip()]

if not allowed_origins:
    allowed_origins = [
        "https://marijuane23.github.io",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=r"https?://.*",  # Supports dynamic preview ports and GitHub Pages domains
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

@app.get("/")
async def root():
    return {
        "message": "Welcome to Image 4K Upscaler API",
        "status": "online",
        "docs": "/docs",
        "health": "/health"
    }

from routes.enhance import router as enhance_router

app.include_router(enhance_router)

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "image-4k-upscaler-api",
        "version": "1.0.0"
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
