"""Loads the trained YOLOv8 classification model and predicts a fruit."""
import io
import os

from PIL import Image, ImageOps

import config


def load_model(path: str | None = None):
    path = path or config.MODEL_PATH
    if not os.path.exists(path) and os.path.exists("best.pt"):
        path = "best.pt"
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Model file not found: {path}. Copy your trained 'best.pt' into the 'models' folder."
        )
    from ultralytics import YOLO

    return YOLO(path)


def open_image(file) -> Image.Image:
    """Opens an uploaded image, fixes phone rotation, returns RGB."""
    return ImageOps.exif_transpose(Image.open(file)).convert("RGB")


def predict(model, image: Image.Image):
    """Returns a list of (label, probability) sorted from best to worst."""
    result = model.predict(image, verbose=False)[0]
    probs = result.probs.data.tolist()
    ranked = [(result.names[i], float(p)) for i, p in enumerate(probs)]
    ranked.sort(key=lambda item: item[1], reverse=True)
    return ranked


def make_thumbnail(image: Image.Image, size: int = 400) -> bytes:
    thumb = image.copy()
    thumb.thumbnail((size, size))
    buffer = io.BytesIO()
    thumb.save(buffer, format="JPEG", quality=80)
    return buffer.getvalue()
