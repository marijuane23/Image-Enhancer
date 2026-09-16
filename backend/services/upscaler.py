import os
import time
import math
import logging
from pathlib import Path
from typing import Tuple, Dict, Any, Optional
from PIL import Image, ImageFilter, ImageOps

logger = logging.getLogger("upscaler")

BASE_DIR = Path(__file__).resolve().parent.parent
WEIGHTS_DIR = BASE_DIR / "weights"
WEIGHTS_DIR.mkdir(parents=True, exist_ok=True)

MODEL_URL = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth"
MODEL_PATH = WEIGHTS_DIR / "RealESRGAN_x4plus.pth"

# Lazy-loaded global model cache
_loaded_model = None
_torch_available = False

try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    import numpy as np
    _torch_available = True
except ImportError:
    _torch_available = False


class ResidualDenseBlock(nn.Module if _torch_available else object):
    def __init__(self, num_feat=64, num_grow_ch=32):
        super().__init__()
        self.conv1 = nn.Conv2d(num_feat, num_grow_ch, 3, 1, 1)
        self.conv2 = nn.Conv2d(num_feat + num_grow_ch, num_grow_ch, 3, 1, 1)
        self.conv3 = nn.Conv2d(num_feat + 2 * num_grow_ch, num_grow_ch, 3, 1, 1)
        self.conv4 = nn.Conv2d(num_feat + 3 * num_grow_ch, num_grow_ch, 3, 1, 1)
        self.conv5 = nn.Conv2d(num_feat + 4 * num_grow_ch, num_feat, 3, 1, 1)
        self.lrelu = nn.LeakyReLU(negative_slope=0.2, inplace=True)

    def forward(self, x):
        x1 = self.lrelu(self.conv1(x))
        x2 = self.lrelu(self.conv2(torch.cat((x, x1), 1)))
        x3 = self.lrelu(self.conv3(torch.cat((x, x1, x2), 1)))
        x4 = self.lrelu(self.conv4(torch.cat((x, x1, x2, x3), 1)))
        x5 = self.conv5(torch.cat((x, x1, x2, x3, x4), 1))
        return x5 * 0.2 + x


class RRDB(nn.Module if _torch_available else object):
    def __init__(self, num_feat=64, num_grow_ch=32):
        super().__init__()
        self.rdb1 = ResidualDenseBlock(num_feat, num_grow_ch)
        self.rdb2 = ResidualDenseBlock(num_feat, num_grow_ch)
        self.rdb3 = ResidualDenseBlock(num_feat, num_grow_ch)

    def forward(self, x):
        out = self.rdb1(x)
        out = self.rdb2(out)
        out = self.rdb3(out)
        return out * 0.2 + x


class RRDBNet(nn.Module if _torch_available else object):
    def __init__(self, num_in_ch=3, num_out_ch=3, scale=4, num_feat=64, num_block=23, num_grow_ch=32):
        super().__init__()
        self.scale = scale
        self.conv_first = nn.Conv2d(num_in_ch, num_feat, 3, 1, 1)
        self.body = nn.Sequential(*[RRDB(num_feat, num_grow_ch) for _ in range(num_block)])
        self.conv_body = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
        self.conv_up1 = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
        self.conv_up2 = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
        self.conv_hr = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
        self.conv_last = nn.Conv2d(num_feat, num_out_ch, 3, 1, 1)
        self.lrelu = nn.LeakyReLU(negative_slope=0.2, inplace=True)

    def forward(self, x):
        feat = self.conv_first(x)
        body_feat = self.conv_body(self.body(feat))
        feat = feat + body_feat
        feat = self.lrelu(self.conv_up1(F.interpolate(feat, scale_factor=2, mode='nearest')))
        feat = self.lrelu(self.conv_up2(F.interpolate(feat, scale_factor=2, mode='nearest')))
        out = self.conv_last(self.lrelu(self.conv_hr(feat)))
        return out


def calculate_4k_dimensions(width: int, height: int, max_w: int = 3840, max_h: int = 2160) -> Tuple[int, int, float]:
    """
    Calculate target dimensions that scale the image up to 4K resolution
    while strictly preserving the aspect ratio.
    - If landscape or square: width scales to 3840, height scaled proportionally.
    - If portrait: height scales to 3840 (or 2160 for 16:9 bound), width scaled proportionally.
    """
    if width <= 0 or height <= 0:
        raise ValueError(f"Invalid dimensions: {width}x{height}")

    if width >= height:
        # Landscape / square
        new_width = max_w
        new_height = round(max_w * (height / width))
    else:
        # Portrait (vertical)
        new_height = max_w
        new_width = round(max_w * (width / height))

    # Ensure even dimensions (required by encoders and avoids single-pixel blur)
    new_width = new_width if new_width % 2 == 0 else new_width + 1
    new_height = new_height if new_height % 2 == 0 else new_height + 1

    scale_factor = new_width / width
    return new_width, new_height, scale_factor


def ensure_weights_available() -> bool:
    """Ensure weights file exists; downloads it if missing."""
    if MODEL_PATH.exists() and MODEL_PATH.stat().st_size > 10 * 1024 * 1024:
        return True
    try:
        from download_weights import download_weights
        logger.info(f"Weights not found at {MODEL_PATH}. Initiating automatic download...")
        download_weights()
        return MODEL_PATH.exists()
    except Exception as exc:
        logger.error(f"Error ensuring weights available: {exc}")
        return False


def get_real_esrgan_model():
    """
    Lazy load Real-ESRGAN model onto CPU device.
    """
    global _loaded_model, _torch_available
    if not _torch_available:
        return None

    if _loaded_model is not None:
        return _loaded_model

    if not MODEL_PATH.exists():
        logger.warning(f"Model weights not found at {MODEL_PATH}. Initiating automatic download...")
        if not ensure_weights_available():
            return None

    try:
        model = RRDBNet(num_in_ch=3, num_out_ch=3, scale=4, num_feat=64, num_block=23, num_grow_ch=32)
        checkpoint = torch.load(str(MODEL_PATH), map_location=torch.device('cpu'), weights_only=True)
        keyname = 'params_ema' if 'params_ema' in checkpoint else 'params'
        model.load_state_dict(checkpoint[keyname] if keyname in checkpoint else checkpoint, strict=True)
        model.eval()
        _loaded_model = model
        return _loaded_model
    except Exception as e:
        logger.error(f"Failed to load Real-ESRGAN weights: {e}")
        return None


def run_ai_inference(pil_img: Image.Image, tile_size: int = 256, tile_pad: int = 10) -> Image.Image:
    """
    Run 4x super-resolution inference on PIL Image using Real-ESRGAN model.
    Uses tiled inference on larger images to maintain low CPU memory usage on Render instances.
    """
    global _torch_available
    model = get_real_esrgan_model()
    if model is None or not _torch_available:
        raise RuntimeError("Real-ESRGAN model not available")

    img_np = np.array(pil_img).astype(np.float32) / 255.0
    h, w, c = img_np.shape
    scale = 4

    # Single pass if image is small enough
    if h <= tile_size and w <= tile_size:
        tensor = torch.from_numpy(img_np.transpose(2, 0, 1)).unsqueeze(0)
        with torch.no_grad():
            output_tensor = model(tensor)
        output_np = output_tensor.squeeze(0).clamp(0, 1).numpy().transpose(1, 2, 0)
        return Image.fromarray((output_np * 255.0).round().astype(np.uint8))

    # Tiled inference for large images to prevent OOM (using uint8 array to save 75% RAM)
    out_h, out_w = h * scale, w * scale
    output_np = np.zeros((out_h, out_w, c), dtype=np.uint8)

    tiles_x = math.ceil(w / tile_size)
    tiles_y = math.ceil(h / tile_size)

    with torch.no_grad():
        for yi in range(tiles_y):
            for xi in range(tiles_x):
                # Tile coordinates with padding
                x_start = xi * tile_size
                x_end = min(x_start + tile_size, w)
                y_start = yi * tile_size
                y_end = min(y_start + tile_size, h)

                x_pad_start = max(x_start - tile_pad, 0)
                x_pad_end = min(x_end + tile_pad, w)
                y_pad_start = max(y_start - tile_pad, 0)
                y_pad_end = min(y_end + tile_pad, h)

                tile = img_np[y_pad_start:y_pad_end, x_pad_start:x_pad_end]
                tile_tensor = torch.from_numpy(tile.transpose(2, 0, 1)).unsqueeze(0)

                tile_out = model(tile_tensor).squeeze(0).clamp(0, 1).numpy().transpose(1, 2, 0)

                # Crop out the padding
                crop_top = (y_start - y_pad_start) * scale
                crop_bottom = crop_top + (y_end - y_start) * scale
                crop_left = (x_start - x_pad_start) * scale
                crop_right = crop_left + (x_end - x_start) * scale

                cropped_tile = (tile_out[crop_top:crop_bottom, crop_left:crop_right] * 255.0).round().astype(np.uint8)

                # Stitch into final output
                output_np[y_start * scale:y_end * scale, x_start * scale:x_end * scale] = cropped_tile

    return Image.fromarray(output_np)


def run_enhanced_fallback(pil_img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """
    High-fidelity Lanczos resampling + detail enhancement filter.
    Provides fast, crisp, reliable scaling with clear edge definition.
    """
    upscaled = pil_img.resize((target_w, target_h), Image.Resampling.LANCZOS)
    sharpened = upscaled.filter(ImageFilter.UnsharpMask(radius=2.2, percent=160, threshold=2))
    from PIL import ImageEnhance
    contrast = ImageEnhance.Contrast(sharpened).enhance(1.05)
    enhanced = ImageEnhance.Sharpness(contrast).enhance(1.2)
    return enhanced


def enhance_image(
    input_path: str,
    output_path: str,
    engine: str = "auto"
) -> Dict[str, Any]:
    """
    Main enhancement pipeline:
    1. Reads and validates the source image.
    2. Calculates aspect-ratio preserving 4K target dimensions.
    3. Runs Real-ESRGAN AI super-resolution (with graceful high-fidelity fallback).
    4. Resizes to final 4K target and saves output.
    """
    start_time = time.time()
    input_file = Path(input_path)

    if not input_file.exists():
        raise FileNotFoundError(f"Input image not found: {input_path}")

    # 1. Open and validate input image
    try:
        with Image.open(input_file) as raw_img:
            # Handle EXIF orientation if present
            raw_img = ImageOps.exif_transpose(raw_img)
            # Ensure RGB mode (handling PNG transparency via white background)
            if raw_img.mode in ("RGBA", "LA") or (raw_img.mode == "P" and "transparency" in raw_img.info):
                img = Image.new("RGB", raw_img.size, (255, 255, 255))
                img.paste(raw_img, mask=raw_img.convert("RGBA").split()[3])
            else:
                img = raw_img.convert("RGB")

            orig_w, orig_h = img.size
    except Exception as e:
        raise ValueError(f"Corrupt or unreadable image file: {e}")

    # 2. Compute 4K target resolution
    target_w, target_h, scale_factor = calculate_4k_dimensions(orig_w, orig_h)

    # 3. Choose engine and process
    engine_used = "Lanczos High-Fidelity + Edge Enhancement"
    enhanced_img = None

    if engine in ("auto", "ai"):
        try:
            # Pre-cap input dimension if excessively large to protect CPU & Render 512MB RAM
            max_ai_dim = 1920
            ai_input = img
            if max(orig_w, orig_h) > max_ai_dim:
                scale_down = max_ai_dim / max(orig_w, orig_h)
                new_w = round(orig_w * scale_down)
                new_h = round(orig_h * scale_down)
                ai_input = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

            enhanced_img = run_ai_inference(ai_input)
            engine_used = "Real-ESRGAN Super-Resolution (AI)"
        except Exception as e:
            logger.info(f"AI engine not active or failed ({e}), using enhanced Lanczos pipeline.")
            enhanced_img = None

    if enhanced_img is None:
        enhanced_img = run_enhanced_fallback(img, target_w, target_h)
    else:
        # If AI model ran (4x output), adjust to exact 4K target
        if enhanced_img.size != (target_w, target_h):
            enhanced_img = enhanced_img.resize((target_w, target_h), Image.Resampling.LANCZOS)

    # 4. Save enhanced image
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    # Select save format based on extension
    ext = output_file.suffix.lower()
    if ext in (".jpg", ".jpeg"):
        enhanced_img.save(str(output_file), "JPEG", quality=95, optimize=True)
    elif ext == ".webp":
        enhanced_img.save(str(output_file), "WEBP", quality=95)
    else:
        enhanced_img.save(str(output_file), "PNG", optimize=True)

    elapsed = time.time() - start_time
    final_w, final_h = enhanced_img.size

    return {
        "status": "completed",
        "engine": engine_used,
        "input_dimensions": {"width": orig_w, "height": orig_h},
        "output_dimensions": {"width": final_w, "height": final_h},
        "target_4k": True,
        "scale_factor": round(scale_factor, 2),
        "processing_time_sec": round(elapsed, 3),
        "output_path": str(output_file)
    }
