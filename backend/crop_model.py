"""Crop-disease image classifier (MobileNetV2, 39 output classes).

The model is loaded lazily and the rest of the API keeps working if it cannot be
loaded (TensorFlow/Keras not installed, model file missing, ...). In that case
``status()`` explains why and the API falls back to image-quality feedback only.

Class order
-----------
``models/class_names.json`` lists the 39 labels in output-index order. That is the
alphabetical folder order Keras' ``flow_from_directory`` produces for the PlantVillage
"without augmentation" dataset (38 PlantVillage classes plus
``Background_without_leaves``). It was checked against the shipped weights with real
PlantVillage photos; see ``scripts/check_crop_model.py`` to repeat that check.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

logger = logging.getLogger("krishisaathi.crop_model")

MODELS_DIR = Path(__file__).parent / "models"
FIELD_MODEL_PATH = MODELS_DIR / "crop_disease_field_v2.h5"  # fine-tuned on field photos (see training/)
LAB_MODEL_PATH = MODELS_DIR / "crop_disease_mobilenetv2_final.h5"  # original PlantVillage-only model
DEFAULT_MODEL_PATH = FIELD_MODEL_PATH if FIELD_MODEL_PATH.is_file() else LAB_MODEL_PATH
MODEL_CARD_PATH = MODELS_DIR / "model_card.json"
DEFAULT_CLASS_NAMES_PATH = MODELS_DIR / "class_names.json"
IMAGE_SIZE = (224, 224)
BACKGROUND_LABEL = "Background_without_leaves"
LOW_CONFIDENCE_THRESHOLD = 0.60


@dataclass
class Prediction:
    label: str
    crop: str | None
    condition: str
    healthy: bool
    is_background: bool
    confidence: float
    top: list[dict] = field(default_factory=list)
    evidence: str = "unknown"  # "field" = class was trained and tested on field photos, "lab_only" = lab photos only


def describe_label(label: str) -> tuple[str | None, str]:
    """Turn ``Tomato___Late_blight`` into ``("Tomato", "Late blight")``."""
    if label == BACKGROUND_LABEL:
        return None, "No leaf detected"
    crop, _, condition = label.partition("___")
    clean = lambda text: " ".join(text.replace("_", " ").split())  # noqa: E731
    return clean(crop), clean(condition) or "Unknown"


class CropModel:
    def __init__(self, model_path: Path | str | None = None, class_names_path: Path | str | None = None):
        self.model_path = Path(model_path or os.getenv("CROP_MODEL_PATH") or DEFAULT_MODEL_PATH)
        self.class_names_path = Path(class_names_path or os.getenv("CROP_CLASS_NAMES_PATH") or DEFAULT_CLASS_NAMES_PATH)
        self.temperature, self.threshold, self.class_evidence, self.card = 1.0, LOW_CONFIDENCE_THRESHOLD, {}, {}
        self._model = None
        self._class_names: list[str] = []
        self._error: str | None = None
        self._loaded = False
        self._lock = threading.RLock()
        self._cam_model = None

    # ----- availability ---------------------------------------------------------------
    def _read_model_card(self) -> None:
        """Optional settings written by training/train_field_model.py. Missing card = neutral defaults."""
        self.temperature, self.threshold, self.class_evidence, self.card = 1.0, LOW_CONFIDENCE_THRESHOLD, {}, {}
        card_path = MODEL_CARD_PATH if self.model_path == FIELD_MODEL_PATH else None
        if card_path is None or not card_path.is_file():
            return
        try:
            card = json.loads(card_path.read_text(encoding="utf-8"))
            self.temperature = float(card.get("temperature", 1.0))
            self.threshold = float(card.get("low_confidence_threshold", LOW_CONFIDENCE_THRESHOLD))
            self.class_evidence = dict(card.get("class_evidence", {}))
            self.card = card
        except (OSError, ValueError, TypeError):
            logger.warning("model_card.json could not be read; using defaults")

    def _precheck(self) -> str | None:
        """Cheap checks that do not import TensorFlow."""
        if not self.model_path.is_file():
            return f"Model file not found: {self.model_path.name}"
        if not self.class_names_path.is_file():
            return f"Class-name file not found: {self.class_names_path.name}"
        if importlib.util.find_spec("keras") is None or importlib.util.find_spec("tensorflow") is None:
            return "TensorFlow/Keras is not installed. Run: pip install -r requirements.txt"
        return None

    def status(self) -> dict:
        error = self._error or (None if self._loaded else self._precheck())
        return {
            "available": error is None,
            "loaded": self._loaded,
            "classes": len(self._class_names) or None,
            "model_file": self.model_path.name,
            "field_tuned": self.model_path == FIELD_MODEL_PATH,
            "error": error,
        }

    # ----- loading --------------------------------------------------------------------
    def load(self) -> bool:
        """Load weights once. Returns True when the model can serve predictions."""
        with self._lock:
            if self._loaded:
                return True
            if self._error:
                return False
            problem = self._precheck()
            if problem:
                self._error = problem
                return False
            try:
                os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
                import keras  # imported lazily: it is slow and optional

                names = json.loads(self.class_names_path.read_text(encoding="utf-8"))
                if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
                    raise ValueError("class_names.json must be a JSON list of strings")
                model = keras.models.load_model(self.model_path, compile=False)
                outputs = int(model.output_shape[-1])
                if outputs != len(names):
                    raise ValueError(f"model has {outputs} outputs but class_names.json lists {len(names)} classes")
                if tuple(model.input_shape[1:3]) != IMAGE_SIZE:
                    raise ValueError(f"unexpected model input shape {model.input_shape}")
                self._model, self._class_names, self._loaded = model, names, True
                self._read_model_card()
                logger.info("Crop model loaded (%d classes)", len(names))
                return True
            except Exception as exc:  # noqa: BLE001 - any failure must degrade gracefully
                logger.exception("Could not load the crop disease model")
                self._error = f"Model could not be loaded: {type(exc).__name__}: {exc}"
                return False

    # ----- inference ------------------------------------------------------------------
    @staticmethod
    def preprocess(image: Image.Image) -> np.ndarray:
        # RGB, 224x224, scaled to [0, 1]. BILINEAR (antialiased when shrinking) is used for training
        # and inference alike. The original lab-trained model used NEAREST, which aliases badly on
        # large phone photos; see training/train_field_model.py.
        resized = image.convert("RGB").resize(IMAGE_SIZE, Image.BILINEAR)
        return np.asarray(resized, dtype="float32")[None, ...] / 255.0

    def predict(self, image: Image.Image, top_k: int = 3) -> Prediction:
        if not self.load():
            raise RuntimeError(self._error or "Crop model unavailable")
        batch = self.preprocess(image)
        with self._lock:  # one inference at a time keeps memory use predictable
            scores = np.asarray(self._model.predict(batch, verbose=0))[0]
        scores = self._calibrate(scores)
        order = np.argsort(scores)[::-1][:top_k]
        top = []
        for index in order:
            label = self._class_names[int(index)]
            crop, condition = describe_label(label)
            top.append({"label": label, "crop": crop, "condition": condition, "confidence": float(scores[index])})
        best = top[0]
        return Prediction(
            label=best["label"],
            crop=best["crop"],
            condition=best["condition"],
            healthy=best["condition"].lower() == "healthy",
            is_background=best["label"] == BACKGROUND_LABEL,
            confidence=best["confidence"],
            top=top,
            evidence=self.class_evidence.get(best["label"], "unknown"),
        )

    def _calibrate(self, scores: np.ndarray) -> np.ndarray:
        """Temperature scaling fitted on held-out field photos (see model_card.json). T=1 changes nothing."""
        if abs(self.temperature - 1.0) < 1e-9:
            return scores
        logits = np.log(np.clip(scores, 1e-12, 1.0)) / self.temperature
        logits -= logits.max()
        exp = np.exp(logits)
        return exp / exp.sum()

    def explain(self, image: Image.Image, class_index: int | None = None) -> bytes:
        """Grad-CAM overlay (JPEG bytes) showing which image regions pushed the model toward a class.

        It explains what the model looked at, not whether the model is right: a heat-map on a
        wrong answer usually highlights the wrong thing, which is exactly why it is shown.
        """
        if not self.load():
            raise RuntimeError(self._error or "Crop model unavailable")
        import io

        import tensorflow as tf

        rgb = image.convert("RGB")
        batch = tf.convert_to_tensor(self.preprocess(rgb))
        with self._lock:
            if self._cam_model is None:
                self._cam_model = tf.keras.Model(self._model.input, [self._model.get_layer("out_relu").output, self._model.output])
            with tf.GradientTape() as tape:
                features, scores = self._cam_model(batch, training=False)
                index = int(np.argmax(scores[0])) if class_index is None else class_index
                target = scores[:, index]
            grads = tape.gradient(target, features)
            weights = tf.reduce_mean(grads, axis=(1, 2), keepdims=True)
            cam = tf.nn.relu(tf.reduce_sum(weights * features, axis=-1))[0].numpy()
        cam = cam / cam.max() if cam.max() > 0 else cam
        side = 384
        base = rgb.copy()
        base.thumbnail((side, side))
        heat = Image.fromarray((cam * 255).astype("uint8")).resize(base.size, Image.BICUBIC)
        h = np.asarray(heat, dtype=np.float32) / 255.0
        # simple red-yellow ramp: no matplotlib dependency
        colour = np.stack([np.clip(h * 2, 0, 1), np.clip(h * 2 - 0.6, 0, 1) * 0.9, np.zeros_like(h)], axis=-1) * 255
        alpha = (h * 0.65)[..., None]
        blended = np.asarray(base, dtype=np.float32) * (1 - alpha) + colour * alpha
        out = io.BytesIO()
        Image.fromarray(blended.astype("uint8")).save(out, format="JPEG", quality=82, optimize=True)
        return out.getvalue()


_instance: CropModel | None = None
_instance_lock = threading.Lock()


def get_model() -> CropModel:
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = CropModel()
        return _instance


def set_model(model: CropModel | None) -> None:
    """Replace the shared model (used by tests)."""
    global _instance
    with _instance_lock:
        _instance = model
