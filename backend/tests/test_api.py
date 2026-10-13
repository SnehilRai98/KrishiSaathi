"""Isolated API tests for the current three-module application."""

import io

import importlib.util

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import crop_model
import database
from database import CropAnalysis
from main import app

from .conftest import make_prediction


def make_png() -> bytes:
    image = Image.new("RGB", (16, 16), color=(30, 160, 60))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_health_checks_database_and_reports_model_status(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["database"]["ready"] is True
    assert response.json()["database"]["engine"] == "sqlite"
    assert response.json()["crop_model"]["available"] is False
    assert "not found" in response.json()["crop_model"]["error"]


def test_liveness_does_not_need_database(client):
    database.configure_database("")
    assert client.get("/api/health/live").json() == {"status": "ok"}


def test_invalid_image_extension_is_rejected(client):
    response = client.post("/api/crop-health/predict", files={"image": ("leaf.gif", b"no", "image/gif")})
    assert response.status_code == 400


def test_invalid_image_bytes_are_rejected(client):
    response = client.post("/api/crop-health/predict", files={"image": ("leaf.jpg", b"not an image", "image/jpeg")})
    assert response.status_code == 400


def test_model_unavailable_falls_back_to_image_quality_only(client):
    response = client.post("/api/crop-health/predict", files={"image": ("leaf.png", make_png(), "image/png")})
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "image_quality_only"
    assert result["disease"] is None and result["confidence"] is None
    assert "unavailable" in result["message"]
    history = client.get("/api/crop-health/history").json()
    assert history[0]["image_filename"] == "leaf.png"
    assert history[0]["status"] == "image_quality_only"
    assert history[0]["created_at"].endswith("Z")


def test_confident_disease_prediction_is_returned_and_persisted(client, fake_model):
    fake_model.prediction = make_prediction("Tomato___Late_blight", 0.97)
    result = client.post("/api/crop-health/predict", files={"image": ("leaf.png", make_png(), "image/png")}).json()
    assert result["status"] == "diagnosed"
    assert result["disease"] == "Tomato \u2014 Late blight"
    assert result["crop"] == "Tomato" and result["condition"] == "Late blight" and result["healthy"] is False
    assert result["confidence"] == pytest.approx(0.97)
    assert result["top_predictions"][0]["label"] == "Tomato \u2014 Late blight"
    assert any("agriculture officer" in line for line in result["guidance"])
    row = client.get("/api/crop-health/history").json()[0]
    assert row["disease"] == "Tomato \u2014 Late blight" and row["status"] == "diagnosed"


def test_healthy_leaf_prediction(client, fake_model):
    fake_model.prediction = make_prediction("Apple___healthy", 0.99)
    result = client.post("/api/crop-health/predict", files={"image": ("leaf.png", make_png(), "image/png")}).json()
    assert result["status"] == "diagnosed" and result["healthy"] is True
    assert result["message"].startswith("Looks healthy")


def test_low_confidence_prediction_gives_no_diagnosis(client, fake_model):
    fake_model.prediction = make_prediction("Potato___Early_blight", 0.41)
    result = client.post("/api/crop-health/predict", files={"image": ("leaf.png", make_png(), "image/png")}).json()
    assert result["status"] == "low_confidence"
    assert result["disease"] is None
    assert result["top_predictions"][0]["confidence"] == pytest.approx(0.41)


def test_background_prediction_reports_no_leaf(client, fake_model):
    fake_model.prediction = make_prediction("Background_without_leaves", 0.95)
    result = client.post("/api/crop-health/predict", files={"image": ("leaf.png", make_png(), "image/png")}).json()
    assert result["status"] == "no_leaf_detected" and result["disease"] is None


@pytest.mark.parametrize(
    "label,crop,condition",
    [
        ("Corn_(maize)___Cercospora_leaf_spot Gray_leaf_spot", "Corn (maize)", "Cercospora leaf spot Gray leaf spot"),
        ("Pepper,_bell___healthy", "Pepper, bell", "healthy"),
        ("Corn_(maize)___Common_rust_", "Corn (maize)", "Common rust"),
        ("Background_without_leaves", None, "No leaf detected"),
    ],
)
def test_label_formatting(label, crop, condition):
    assert crop_model.describe_label(label) == (crop, condition)


def test_class_names_file_matches_model_output_size():
    names = crop_model.CropModel().class_names_path.read_text(encoding="utf-8")
    import json
    parsed = json.loads(names)
    assert len(parsed) == 39 and parsed == sorted(parsed)
    assert parsed[4] == crop_model.BACKGROUND_LABEL


@pytest.mark.skipif(
    importlib.util.find_spec("keras") is None or not crop_model.DEFAULT_MODEL_PATH.is_file(),
    reason="TensorFlow/Keras or the bundled model is not available",
)
def test_real_model_loads_and_returns_valid_scores():
    model = crop_model.CropModel()
    assert model.load(), model.status()
    prediction = model.predict(Image.new("RGB", (300, 300), (40, 150, 60)))
    assert 0.0 <= prediction.confidence <= 1.0
    assert len(prediction.top) == 3
    assert prediction.top[0]["confidence"] >= prediction.top[1]["confidence"]


def test_oversized_image_is_rejected(client):
    response = client.post(
        "/api/crop-health/predict",
        files={"image": ("large.png", b"0" * (10 * 1024 * 1024 + 1), "image/png")},
    )
    assert response.status_code == 413


def test_crop_history_empty_state(client):
    response = client.get("/api/crop-health/history")
    assert response.status_code == 200 and response.json() == []


def test_crop_history_reads_database_record(client):
    with database.SessionLocal() as session:
        session.add(CropAnalysis(image_filename="fixture.png", predicted_disease="fixture", confidence=0.5, status="diagnosed"))
        session.commit()
    response = client.get("/api/crop-health/history")
    assert response.status_code == 200 and response.json()[0]["image_filename"] == "fixture.png"


def test_unconfigured_database_reports_clear_unavailable_status(client):
    database.configure_database("")
    with TestClient(app) as unavailable_client:
        health = unavailable_client.get("/api/health")
        plans = unavailable_client.get("/api/fertilizer/history")
    assert health.status_code == 503
    assert plans.status_code == 503


def test_configured_but_unreachable_database_is_not_healthy(client):
    # Port 1 is deliberately closed so this test can never touch a developer's MySQL.
    database.configure_database("mysql+pymysql://test:test@127.0.0.1:1/krishisaathi_test?connect_timeout=1")
    with TestClient(app) as unavailable_client:
        health = unavailable_client.get("/api/health")
        plans = unavailable_client.get("/api/fertilizer/history")
    assert health.status_code == 503
    assert "Cannot connect" in health.json()["detail"]["database"]["error"]
    assert plans.status_code == 503
    assert "Cannot connect" in plans.json()["detail"]


# ----- hardening added in the enhancement pass ----------------------------------------------
def make_image(fmt: str, size=(16, 16)) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", size, (30, 160, 60)).save(output, format=fmt)
    return output.getvalue()


def test_webp_upload_is_accepted(client, fake_model):
    fake_model.prediction = make_prediction("Apple___healthy", 0.97)
    response = client.post("/api/crop-health/predict", files={"image": ("leaf.webp", make_image("WEBP"), "image/webp")})
    assert response.status_code == 200 and response.json()["status"] == "diagnosed"


def test_file_content_must_match_an_allowed_format(client):
    renamed_gif = client.post("/api/crop-health/predict", files={"image": ("leaf.png", make_image("GIF"), "image/png")})
    assert renamed_gif.status_code == 400 and "not a JPG, PNG or WebP" in renamed_gif.json()["detail"]
    text_file = client.post("/api/crop-health/predict", files={"image": ("notes.txt", b"hello", "text/plain")})
    assert text_file.status_code == 400
    no_extension = client.post("/api/crop-health/predict", files={"image": ("leaf", make_image("PNG"), "image/png")})
    assert no_extension.status_code == 400
    assert client.get("/api/crop-health/history").json() == []  # rejected files are not recorded


def test_missing_file_field_is_a_clean_422(client):
    assert client.post("/api/crop-health/predict").status_code == 422


def test_declared_oversized_body_is_rejected_before_reading(client):
    response = client.post("/api/fertilizer/plan", content=b"{}", headers={"content-length": str(50 * 1024 * 1024),
                                                                              "content-type": "application/json"})
    assert response.status_code == 413


def test_top_predictions_are_saved_for_history_details(client, fake_model):
    fake_model.prediction = make_prediction("Tomato___Early_blight", 0.88)
    client.post("/api/crop-health/predict", files={"image": ("leaf.png", make_png(), "image/png")})
    row = client.get("/api/crop-health/history").json()[0]
    assert row["top_predictions"][0]["label"] == "Tomato \u2014 Early blight"
    assert row["top_predictions"][0]["confidence"] == pytest.approx(0.88)


def test_old_history_rows_without_details_still_load(client):
    with database.SessionLocal() as session:
        session.add(CropAnalysis(image_filename="old.png", status="diagnosed", predicted_disease="x", confidence=0.7))
        session.commit()
    assert client.get("/api/crop-health/history").json()[0]["top_predictions"] == []


def test_inference_failure_degrades_to_quality_feedback(client, fake_model):
    fake_model.prediction = make_prediction("Apple___healthy", 0.99)

    def boom(image, top_k=3):
        raise RuntimeError("secret /srv/model/path exploded")

    fake_model.predict = boom
    response = client.post("/api/crop-health/predict", files={"image": ("leaf.png", make_png(), "image/png")})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "image_quality_only" and body["disease"] is None
    assert "secret" not in response.text and "/srv" not in response.text


def test_unexpected_errors_return_generic_json_without_details(client, monkeypatch):
    def explode(*args, **kwargs):
        raise RuntimeError("password=hunter2 at /home/secret/app.py")

    monkeypatch.setattr("main.parse_top_predictions", explode)
    with database.SessionLocal() as session:
        session.add(CropAnalysis(image_filename="a.png", status="diagnosed", top_predictions="[]"))
        session.commit()
    from fastapi.testclient import TestClient
    with TestClient(app, raise_server_exceptions=False) as quiet:
        response = quiet.get("/api/crop-health/history")
    assert response.status_code == 500
    assert "hunter2" not in response.text and "/home" not in response.text and "Traceback" not in response.text




# ----- field-model features: explanations, evidence, model info ------------------------------
def test_heatmap_is_returned_only_when_requested(client, fake_model):
    fake_model.prediction = make_prediction("Tomato___Late_blight", 0.9)
    plain = client.post("/api/crop-health/predict", files={"image": ("leaf.png", make_png(), "image/png")}).json()
    assert plain["heatmap"] is None
    explained = client.post("/api/crop-health/predict?explain=true", files={"image": ("leaf.png", make_png(), "image/png")}).json()
    assert explained["heatmap"].startswith("data:image/jpeg;base64,")


def test_heatmap_failure_does_not_break_the_prediction(client, fake_model):
    fake_model.prediction = make_prediction("Tomato___Late_blight", 0.9)
    fake_model.explain_error = "gradient exploded at /srv/x"
    response = client.post("/api/crop-health/predict?explain=true", files={"image": ("leaf.png", make_png(), "image/png")})
    assert response.status_code == 200 and response.json()["status"] == "diagnosed" and response.json()["heatmap"] is None
    assert "/srv" not in response.text


def test_no_heatmap_for_background_images(client, fake_model):
    fake_model.prediction = make_prediction("Background_without_leaves", 0.95)
    body = client.post("/api/crop-health/predict?explain=true", files={"image": ("x.png", make_png(), "image/png")}).json()
    assert body["status"] == "no_leaf_detected" and body["heatmap"] is None


def test_lab_only_classes_carry_an_extra_warning(client, fake_model):
    fake_model.prediction = make_prediction("Orange___Haunglongbing_(Citrus_greening)", 0.9, evidence="lab_only")
    body = client.post("/api/crop-health/predict", files={"image": ("leaf.png", make_png(), "image/png")}).json()
    assert body["evidence"] == "lab_only" and any("lab photos only" in line for line in body["guidance"])
    fake_model.prediction = make_prediction("Tomato___Late_blight", 0.9, evidence="field")
    body = client.post("/api/crop-health/predict", files={"image": ("leaf.png", make_png(), "image/png")}).json()
    assert not any("lab photos only" in line for line in body["guidance"])


def test_threshold_comes_from_the_model(client, fake_model):
    fake_model.threshold = 0.8
    fake_model.prediction = make_prediction("Tomato___Late_blight", 0.7)
    body = client.post("/api/crop-health/predict", files={"image": ("leaf.png", make_png(), "image/png")}).json()
    assert body["status"] == "low_confidence" and body["low_confidence_threshold"] == 0.8


def test_model_info_endpoint(client, fake_model):
    body = client.get("/api/crop-health/model").json()
    assert "Tomato" in body["supported_crops"] and body["low_confidence_threshold"] == 0.6 and "status" in body


def test_reliability_reports_measured_field_accuracy_for_the_score(client, fake_model):
    fake_model.card = {"metrics": {"field_test": {"n": 236, "dataset": "PlantDoc test split", "selective": [
        {"threshold": 0.5, "coverage": 0.6, "accuracy_when_answered": 0.70},
        {"threshold": 0.6, "coverage": 0.48, "accuracy_when_answered": 0.75},
        {"threshold": 0.8, "coverage": 0.27, "accuracy_when_answered": 0.86}]}}}
    fake_model.prediction = make_prediction("Tomato___Late_blight", 0.83)
    body = client.post("/api/crop-health/predict", files={"image": ("leaf.png", make_png(), "image/png")}).json()
    assert body["reliability"] == {"score_at_least": 0.8, "accuracy_when_answered": 0.86, "share_of_photos_answered": 0.27, "photos_tested": 236, "dataset": "PlantDoc test split"}
    fake_model.prediction = make_prediction("Tomato___Late_blight", 0.65)
    assert client.post("/api/crop-health/predict", files={"image": ("leaf.png", make_png(), "image/png")}).json()["reliability"]["score_at_least"] == 0.6


def test_reliability_is_absent_without_a_model_card_or_a_diagnosis(client, fake_model):
    fake_model.prediction = make_prediction("Tomato___Late_blight", 0.9)
    assert client.post("/api/crop-health/predict", files={"image": ("leaf.png", make_png(), "image/png")}).json()["reliability"] is None
    fake_model.card = {"metrics": {"field_test": {"n": 1, "dataset": "x", "selective": [{"threshold": 0.5, "coverage": 1, "accuracy_when_answered": 0.5}]}}}
    fake_model.prediction = make_prediction("Tomato___Late_blight", 0.3)
    assert client.post("/api/crop-health/predict", files={"image": ("leaf.png", make_png(), "image/png")}).json()["reliability"] is None


def test_answers_that_were_unreliable_in_field_tests_carry_a_warning(client, fake_model):
    fake_model.card = {"metrics": {"field_test": {"n": 236, "dataset": "x", "selective": [], "per_prediction": {
        "Tomato___healthy": {"n_predicted": 9, "precision": 0.33},
        "Tomato___Late_blight": {"n_predicted": 11, "precision": 0.9},
        "Peach___healthy": {"n_predicted": 3, "precision": 0.0}}}}}
    send = lambda: client.post("/api/crop-health/predict", files={"image": ("leaf.png", make_png(), "image/png")}).json()  # noqa: E731
    fake_model.prediction = make_prediction("Tomato___healthy", 0.9)
    assert any("right only 33% of the time" in line and "9 photos" in line for line in send()["guidance"])
    fake_model.prediction = make_prediction("Tomato___Late_blight", 0.9)
    assert not any("right only" in line for line in send()["guidance"])
    fake_model.prediction = make_prediction("Peach___healthy", 0.9)  # too few photos to say anything
    assert not any("right only" in line for line in send()["guidance"])
