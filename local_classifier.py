from io import BytesIO
from pathlib import Path

import joblib
import numpy as np
from PIL import Image

IMAGE_SIZE = (32, 32)
LABELS = {"O": "Organic", "R": "Recyclable"}


def image_features(image_bytes: bytes) -> np.ndarray:
    image = Image.open(BytesIO(image_bytes)).convert("RGB")
    image = image.resize(IMAGE_SIZE, Image.Resampling.BILINEAR)
    pixels = np.asarray(image, dtype=np.float32) / 255.0
    return pixels.reshape(1, -1)


def load_model(model_path: str | Path):
    return joblib.load(model_path)


def predict(image_bytes: bytes, model_path: str | Path) -> tuple[str, float]:
    model = load_model(model_path)
    features = image_features(image_bytes)
    probabilities = model.predict_proba(features)[0]
    class_index = int(np.argmax(probabilities))
    raw_label = str(model.classes_[class_index])
    return LABELS.get(raw_label, raw_label), float(probabilities[class_index])
