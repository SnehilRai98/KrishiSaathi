"""Shared fixtures: each test gets its own in-memory database and a fake crop model."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import crop_model
import database
from main import app


class FakeCropModel:
    """Stands in for the TensorFlow model so tests are fast and deterministic."""

    def __init__(self, prediction: crop_model.Prediction | None = None, error: str | None = None):
        self.prediction = prediction
        self.error = error if prediction is None else None
        self.threshold = 0.6
        self.temperature = 1.0
        self.card = None
        self.explain_error = None

    def load(self) -> bool:
        return self.prediction is not None

    def status(self) -> dict:
        return {"available": self.prediction is not None, "loaded": self.prediction is not None,
                "classes": 39 if self.prediction else None, "error": self.error}

    def predict(self, image, top_k: int = 3):
        return self.prediction

    def explain(self, image, class_index=None) -> bytes:
        if self.explain_error:
            raise RuntimeError(self.explain_error)
        import io

        from PIL import Image

        out = io.BytesIO()
        Image.new("RGB", (4, 4), (255, 0, 0)).save(out, format="JPEG")
        return out.getvalue()


def make_prediction(label: str, confidence: float, evidence: str = "field") -> crop_model.Prediction:
    crop, condition = crop_model.describe_label(label)
    top = [{"label": label, "crop": crop, "condition": condition, "confidence": confidence}]
    return crop_model.Prediction(
        label=label, crop=crop, condition=condition, healthy=condition.lower() == "healthy",
        is_background=label == crop_model.BACKGROUND_LABEL, confidence=confidence, top=top, evidence=evidence,
    )


@pytest.fixture
def fake_model():
    """Default: model unavailable. Tests replace ``fake_model.prediction`` to enable it."""
    model = FakeCropModel(error="Model file not found: crop_disease_mobilenetv2_final.h5")
    crop_model.set_model(model)
    yield model
    crop_model.set_model(None)


@pytest.fixture
def client(fake_model):
    """Give each test its own SQLite DB and restore app globals even on failure."""
    names = ("DATABASE_URL", "engine", "SessionLocal", "_database_initialized", "_database_error")
    original = {name: getattr(database, name) for name in names}
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    database.DATABASE_URL = "sqlite://"
    database.engine = test_engine
    database.SessionLocal = sessionmaker(bind=test_engine, expire_on_commit=False)
    database._database_initialized = False
    database._database_error = None
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        test_engine.dispose()
        for name, value in original.items():
            setattr(database, name, value)
