import os
import re
import time
import json
import uuid
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, UploadFile, File, Form, Query, HTTPException, status, BackgroundTasks
from fastapi.responses import FileResponse
from PIL import Image

from services.upscaler import enhance_image

router = APIRouter(prefix="", tags=["Enhance"])

# Directory setup
BASE_DIR = Path(__file__).resolve().parent.parent
TEMP_DIR = BASE_DIR / "temp"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

# Validation constants
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp"
}

# Auto-cleanup: delete jobs older than this
JOB_TTL_SECONDS = 3600  # 1 hour

# In-memory job state cache
JOBS_STORE: Dict[str, Dict[str, Any]] = {}


def get_job_meta_path(job_id: str) -> Path:
    return TEMP_DIR / f"{job_id}_meta.json"


def save_job(job_id: str, data: Dict[str, Any]):
    data["updated_at"] = datetime.utcnow().isoformat() + "Z"
    JOBS_STORE[job_id] = data
    try:
        with open(get_job_meta_path(job_id), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Warning: Failed to persist job meta to disk: {e}")


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    if job_id in JOBS_STORE:
        return JOBS_STORE[job_id]
    
    meta_path = get_job_meta_path(job_id)
    if meta_path.exists():
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                JOBS_STORE[job_id] = data
                return data
        except Exception:
            return None
    return None


def cleanup_old_jobs():
    """
    Phase 5: Auto-cleanup.
    Scans the temp directory and removes input/output image files and
    meta JSON files for any job whose created_at timestamp is older
    than JOB_TTL_SECONDS.  Also evicts the job from the in-memory cache.
    Safe to call from a background task.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=JOB_TTL_SECONDS)
    purged = 0

    for meta_path in TEMP_DIR.glob("*_meta.json"):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            created_at_str = data.get("created_at", "")
            if not created_at_str:
                continue
            created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
            if created_at < cutoff:
                job_id = data.get("job_id", "")
                # Remove input + output files
                for path_key in ("input_path", "output_path"):
                    fpath = data.get(path_key)
                    if fpath:
                        p = Path(fpath)
                        if p.exists():
                            try:
                                p.unlink()
                            except Exception:
                                pass
                # Remove any format-converted output files
                if job_id:
                    for conv_file in TEMP_DIR.glob(f"{job_id}_converted_*"):
                        try:
                            conv_file.unlink()
                        except Exception:
                            pass
                # Remove meta file
                try:
                    meta_path.unlink()
                except Exception:
                    pass
                # Evict from in-memory store
                JOBS_STORE.pop(job_id, None)
                purged += 1
        except Exception:
            continue

    if purged:
        print(f"[cleanup] Purged {purged} expired job(s) from temp storage.")
    return purged


def run_background_enhancement(
    job_id: str,
    input_path: str,
    output_path: str,
    engine: str
):
    """
    Background worker that executes the super-resolution pipeline,
    updates progress states, and records completion or failure.
    """
    job = get_job(job_id)
    if not job:
        return

    def update_progress(pct: int, msg: str):
        j = get_job(job_id)
        if j:
            j["status"] = "processing" if pct < 100 else "completed"
            j["progress"] = pct
            j["progress_message"] = msg
            save_job(job_id, j)

    try:
        update_progress(15, "Initializing 4K enhancement pipeline...")

        # 2. Run enhancement pipeline with live progress reporting
        result = enhance_image(
            input_path,
            output_path,
            engine=engine,
            progress_callback=update_progress
        )

        # 3. Mark completed
        job = get_job(job_id)
        if job:
            job["status"] = "completed"
            job["progress"] = 100
            job["progress_message"] = "Enhancement complete! 4K output ready."
            job["completed_at"] = datetime.utcnow().isoformat() + "Z"
            job["result"] = result
            save_job(job_id, job)

    except Exception as exc:
        job = get_job(job_id)
        if job:
            job["status"] = "failed"
            job["progress"] = 100
            job["progress_message"] = "Processing failed."
            job["error"] = str(exc)
            job["failed_at"] = datetime.utcnow().isoformat() + "Z"
            save_job(job_id, job)


@router.post("/enhance", status_code=status.HTTP_202_ACCEPTED)
async def upload_and_enhance(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    engine: str = Query("auto", description="Upscaling engine to use: 'auto', 'ai', or 'fast'")
) -> Dict[str, Any]:
    """
    Accept image file upload, validate format & size, schedule asynchronous
    enhancement job in BackgroundTasks, and return job tracking metadata.
    """
    # 1. Validate content type
    content_type = file.content_type or ""
    if content_type.lower() not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file format '{content_type}'. Allowed formats: JPG, PNG, WEBP."
        )

    ext = ALLOWED_CONTENT_TYPES[content_type.lower()]
    job_id = str(uuid.uuid4())
    temp_input_filename = f"{job_id}_input{ext}"
    temp_output_filename = f"{job_id}_output{ext}"
    temp_input_path = TEMP_DIR / temp_input_filename
    temp_output_path = TEMP_DIR / temp_output_filename

    # 2. Stream file to disk with 10MB limit enforcement
    size_bytes = 0
    chunk_size = 1024 * 1024  # 1MB chunks

    try:
        with open(temp_input_path, "wb") as buffer:
            while True:
                chunk = await file.read(chunk_size)
                if not chunk:
                    break
                size_bytes += len(chunk)
                if size_bytes > MAX_FILE_SIZE:
                    buffer.close()
                    if temp_input_path.exists():
                        temp_input_path.unlink()
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"File exceeds maximum allowed size of {MAX_FILE_SIZE // (1024 * 1024)} MB."
                    )
                buffer.write(chunk)
    except HTTPException:
        raise
    except Exception as e:
        if temp_input_path.exists():
            temp_input_path.unlink()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error saving uploaded file: {str(e)}"
        )

    # 3. Validate image integrity and dimensions
    try:
        with Image.open(temp_input_path) as img:
            img.verify()
        with Image.open(temp_input_path) as img:
            width, height = img.size
            img_format = img.format
    except Exception:
        if temp_input_path.exists():
            temp_input_path.unlink()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded file is corrupt or not a valid image."
        )

    # 4. Create initial Job record
    now_iso = datetime.utcnow().isoformat() + "Z"
    job_data = {
        "job_id": job_id,
        "filename": file.filename,
        "content_type": content_type,
        "size_bytes": size_bytes,
        "dimensions": {"width": width, "height": height},
        "format": img_format,
        "engine_requested": engine,
        "status": "queued",
        "progress": 10,
        "progress_message": "Image queued for 4K super-resolution processing...",
        "created_at": now_iso,
        "updated_at": now_iso,
        "input_path": str(temp_input_path),
        "output_path": str(temp_output_path),
        "result": None,
        "error": None
    }
    save_job(job_id, job_data)

    # 5. Schedule async execution
    background_tasks.add_task(
        run_background_enhancement,
        job_id=job_id,
        input_path=str(temp_input_path),
        output_path=str(temp_output_path),
        engine=engine
    )

    return {
        "job_id": job_id,
        "filename": file.filename,
        "content_type": content_type,
        "size_bytes": size_bytes,
        "dimensions": {"width": width, "height": height},
        "format": img_format,
        "status": "queued",
        "progress": 10,
        "status_url": f"/status/{job_id}",
        "message": "Image successfully uploaded and background enhancement started"
    }


@router.get("/status/{job_id}")
async def get_job_status(job_id: str) -> Dict[str, Any]:
    """
    Poll the status of an ongoing or completed upscaling job.
    """
    job = get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' not found."
        )

    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "progress": job.get("progress", 0),
        "progress_message": job.get("progress_message", ""),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
        "completed_at": job.get("completed_at"),
        "result": job.get("result"),
        "error": job.get("error"),
        "download_url": f"/download/{job_id}" if job["status"] == "completed" else None,
        "preview_url": f"/preview/{job_id}" if job["status"] == "completed" else None
    }


@router.get("/download/{job_id}")
async def download_enhanced_image(
    job_id: str,
    format: Optional[str] = Query(None, description="Target image format: png, jpg, jpeg, webp")
):
    """
    Download the final enhanced 4K image file, optionally converting to the requested
    format (png, jpg, jpeg, webp) on the fly.
    """
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")

    if job["status"] != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Job is not completed yet (current status: {job['status']})."
        )

    output_path = Path(job["output_path"])
    if not output_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Enhanced image file missing from disk.")

    original_stem = Path(job.get("filename", "enhanced")).stem
    safe_stem = re.sub(r'[^\w\-]', '_', original_stem)

    valid_formats = {"png", "jpg", "jpeg", "webp"}
    req_format = format.lower().strip().lstrip(".") if format else None

    if req_format and req_format not in valid_formats:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported format '{format}'. Supported formats: {', '.join(sorted(valid_formats))}."
        )

    current_ext = output_path.suffix.lower().lstrip(".")
    target_ext = req_format if req_format else current_ext
    target_ext_normalized = "jpg" if target_ext == "jpeg" else target_ext
    current_ext_normalized = "jpg" if current_ext == "jpeg" else current_ext

    # Check if conversion is required
    if req_format and (target_ext_normalized != current_ext_normalized):
        converted_filename = f"{job_id}_converted_{target_ext_normalized}.{target_ext_normalized}"
        converted_path = TEMP_DIR / converted_filename

        if not converted_path.exists():
            try:
                with Image.open(output_path) as img:
                    if target_ext_normalized in ("jpg", "jpeg"):
                        # Handle RGBA / transparency gracefully by flattening onto a white background
                        if img.mode in ("RGBA", "LA", "P"):
                            bg = Image.new("RGB", img.size, (255, 255, 255))
                            alpha = img.split()[-1] if img.mode in ("RGBA", "LA") else None
                            bg.paste(img.convert("RGB"), mask=alpha)
                            bg.save(converted_path, format="JPEG", quality=95)
                        else:
                            img.convert("RGB").save(converted_path, format="JPEG", quality=95)
                    elif target_ext_normalized == "webp":
                        img.save(converted_path, format="WEBP", quality=95)
                    elif target_ext_normalized == "png":
                        img.save(converted_path, format="PNG", compress_level=6)
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to convert image to {target_ext}: {e}"
                )

        serve_path = converted_path
    else:
        serve_path = output_path

    # MIME types mapping
    media_types = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp"
    }
    media_type = media_types.get(target_ext, "application/octet-stream")
    download_filename = f"{safe_stem}-4k.{target_ext}"

    return FileResponse(
        path=str(serve_path),
        media_type=media_type,
        filename=download_filename,
        headers={"Content-Disposition": f'attachment; filename="{download_filename}"'}
    )


@router.get("/preview/{job_id}")
async def preview_enhanced_image(job_id: str):
    """
    Stream the enhanced 4K image for browser display and comparison previews.
    """
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")

    if job["status"] != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Job is not completed yet (current status: {job['status']})."
        )

    output_path = Path(job["output_path"])
    if not output_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Enhanced image file not found.")

    return FileResponse(
        path=str(output_path),
        media_type=job.get("content_type", "image/png")
    )
