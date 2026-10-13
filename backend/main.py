"""FastAPI application for KrishiSaathi: crop health detection and the fertiliser planner."""

import json
import logging
import base64
import os
import threading
import warnings
from contextlib import asynccontextmanager
from io import BytesIO

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from PIL import Image, UnidentifiedImageError
from sqlalchemy.orm import Session

import config
import crop_model
import database
import fertilizer_engine as engine
from database import CropAnalysis, FertilizerPlan
from schemas import PlanRequest

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("krishisaathi")

MAX_UPLOAD_BYTES = config.MAX_UPLOAD_BYTES
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}  # what Pillow reports after decoding
# A request body slightly above the upload limit is rejected before it is read in full.
MAX_REQUEST_BYTES = MAX_UPLOAD_BYTES + 512 * 1024
SUPPORTED_CROPS = (
    "Apple, Blueberry, Cherry, Corn (maize), Grape, Orange, Peach, Bell pepper, "
    "Potato, Raspberry, Soybean, Squash, Strawberry and Tomato"
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        database.init_db()
    except Exception:
        # Keep health diagnostics available; DB-backed endpoints and /api/health
        # report the problem with a clear 503 instead of crashing the process.
        logger.exception("KrishiSaathi database initialization failed")
    # Warm the crop model in the background so the first upload is not slow.
    threading.Thread(target=lambda: crop_model.get_model().load(), daemon=True).start()
    yield


app = FastAPI(
    title="KrishiSaathi API",
    version="4.0.0",
    description="Field-tuned crop disease screening and a fertiliser plan calculator",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv(
            "CORS_ORIGINS",
            "http://localhost:8080,http://127.0.0.1:8080,http://localhost:5173,http://127.0.0.1:5173",
        ).split(",")
        if origin.strip()
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.middleware("http")
async def limit_request_size(request: Request, call_next):
    """Reject oversized bodies early using Content-Length (the upload is also re-checked while reading)."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_REQUEST_BYTES:
        return JSONResponse(status_code=413, content={"detail": f"Request is too large (limit {config.MAX_UPLOAD_MB} MB)."})
    return await call_next(request)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    """422 with only location and message. The default body echoes the raw input, which can
    be un-serialisable (NaN) or unwelcome to repeat back."""
    issues = [{"loc": [str(part) for part in error.get("loc", ())], "msg": str(error.get("msg", "Invalid value"))}
              for error in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": issues})


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    """Log the details server-side; never send stack traces or file paths to the browser."""
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Something went wrong on the server. Please try again."})


def iso_utc(moment) -> str:
    """Rows store naive UTC; tell clients so they convert to local time correctly."""
    return moment.isoformat() + "Z"


@app.get("/api/health")
def health() -> dict:
    database_ready, database_error = database.database_status()
    result = {
        "status": "ok" if database_ready else "degraded",
        "database": {
            "ready": database_ready,
            "error": database_error,
            "engine": database.engine.dialect.name if database.engine is not None else None,
        },
        "crop_model": crop_model.get_model().status(),
    }
    if not database_ready:
        raise HTTPException(status_code=503, detail=result)
    return result


@app.get("/api/health/live")
def liveness() -> dict:
    return {"status": "ok"}


def quality_feedback(width: int, height: int, luminance_range: int) -> list[str]:
    feedback = []
    if min(width, height) < 256:
        feedback.append("The image is small; a closer, higher-resolution leaf photo gives a more reliable result.")
    if luminance_range < 35:
        feedback.append("The image has low contrast; try even natural light and avoid strong shadows.")
    return feedback


@app.post("/api/crop-health/predict")
async def predict_crop(
    image: UploadFile = File(...),
    explain: bool = Query(False, description="Also return a Grad-CAM heat-map of what the model looked at"),
    session: Session = Depends(database.get_session),
) -> dict:
    filename = image.filename or ""
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Upload a JPG, PNG or WebP image.")

    content = await image.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"Image must be {config.MAX_UPLOAD_MB} MB or smaller.")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            Image.open(BytesIO(content)).verify()
        with Image.open(BytesIO(content)) as opened:
            if opened.format not in ALLOWED_IMAGE_FORMATS:
                # The file name said JPG/PNG/WebP but the content is something else (e.g. a renamed GIF).
                raise HTTPException(status_code=400, detail="The file content is not a JPG, PNG or WebP image.")
            decoded = opened.convert("RGB")
        width, height = decoded.size
        luminance_range = max(high - low for low, high in decoded.getextrema())
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise HTTPException(status_code=400, detail="The uploaded file is not a safe, decodable image.") from exc

    guidance = quality_feedback(width, height, luminance_range)
    model = crop_model.get_model()
    prediction = None
    model_error = None
    if model.load():
        try:
            prediction = await run_in_threadpool(model.predict, decoded)
        except Exception:  # noqa: BLE001
            logger.exception("Crop model inference failed")
            model_error = "The disease model failed on this image."
    else:
        model_error = model.status()["error"]

    disease = None
    if prediction is None:
        status = "image_quality_only"
        message = f"Disease detection is currently unavailable ({model_error}). Only image-quality feedback is shown."
        if not guidance:
            guidance.append("Image size and contrast look usable; this is not a plant-health assessment.")
    elif prediction.is_background:
        status = "no_leaf_detected"
        message = "No leaf was detected. Take a close, well-lit photo of a single leaf and try again."
    elif prediction.confidence < model.threshold:
        status = "low_confidence"
        message = (
            "The model is not confident about this image, so no result is given. "
            "Try a sharper, closer photo of one leaf, or ask a local agriculture officer."
        )
    else:
        status = "diagnosed"
        disease = f"{prediction.crop} \u2014 {prediction.condition}"
        message = (
            f"Looks healthy: {prediction.crop}." if prediction.healthy
            else f"Possible {prediction.condition.lower()} on {prediction.crop.lower()}."
        )
        guidance.append(
            "This is a screening aid, not a diagnosis. Confirm with your local agriculture officer or "
            "Krishi Vigyan Kendra before spraying or treating."
        )
    if prediction is not None:
        guidance.append(f"The model only knows these crops: {SUPPORTED_CROPS}. Results for other plants are unreliable.")

    if prediction is not None and prediction.evidence == "lab_only" and status == "diagnosed":
        guidance.append(
            "This class was learned from lab photos only and has not been tested on field photos, so the result is less trustworthy than others."
        )
    if prediction is not None and status == "diagnosed":
        note = weak_answer_note(model, prediction.label)
        if note:
            guidance.append(note)
    heatmap = None
    if explain and prediction is not None and not prediction.is_background:
        try:
            overlay = await run_in_threadpool(model.explain, decoded)
            heatmap = "data:image/jpeg;base64," + base64.b64encode(overlay).decode("ascii")
        except Exception:  # noqa: BLE001 - the explanation is optional
            logger.exception("Grad-CAM failed")
    top_predictions = [
        {"label": f"{item['crop']} \u2014 {item['condition']}" if item["crop"] else item["condition"],
         "confidence": item["confidence"]}
        for item in (prediction.top if prediction else [])
    ]
    best_label = None if prediction is None or prediction.is_background else f"{prediction.crop} \u2014 {prediction.condition}"
    row = CropAnalysis(
        image_filename=filename[:255] or "uploaded-image",
        predicted_disease=best_label,
        confidence=prediction.confidence if prediction else None,
        status=status,
        image_width=width,
        image_height=height,
        quality_feedback=" ".join([message, *guidance]),
        top_predictions=json.dumps(top_predictions) if top_predictions else None,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return {
        "id": row.id,
        "status": status,
        "disease": disease,
        "crop": prediction.crop if prediction and status == "diagnosed" else None,
        "condition": prediction.condition if prediction and status == "diagnosed" else None,
        "healthy": prediction.healthy if prediction and status == "diagnosed" else None,
        "confidence": prediction.confidence if prediction else None,
        "top_predictions": top_predictions,
        "low_confidence_threshold": model.threshold,
        "evidence": prediction.evidence if prediction else None,
        "reliability": reliability_for(model, prediction.confidence) if prediction and status == "diagnosed" else None,
        "heatmap": heatmap,
        "image": {"width": width, "height": height},
        "guidance": guidance,
        "message": message,
        "created_at": iso_utc(row.created_at),
    }


def reliability_for(model, confidence: float | None) -> dict | None:
    """What the field test measured for photos that scored like this one (None when there is no test data)."""
    try:
        field = model.card["metrics"]["field_test"]
        rows = [row for row in field["selective"] if row["accuracy_when_answered"] is not None and row["threshold"] <= confidence]
    except (TypeError, KeyError):
        return None
    if confidence is None or not rows:
        return None
    row = max(rows, key=lambda item: item["threshold"])
    return {
        "score_at_least": row["threshold"],
        "accuracy_when_answered": row["accuracy_when_answered"],
        "share_of_photos_answered": row["coverage"],
        "photos_tested": field["n"],
        "dataset": field["dataset"],
    }


def weak_answer_note(model, label: str) -> str | None:
    """Warn when this particular answer was unreliable in the field test (right less than half the time)."""
    try:
        row = model.card["metrics"]["field_test"]["per_prediction"][label]
    except (TypeError, KeyError):
        return None
    if row["n_predicted"] >= 5 and row["precision"] < 0.5:
        return (
            f"In field tests this particular answer was right only {round(row['precision'] * 100)}% of the time "
            f"({row['n_predicted']} photos where the model said it), so check it carefully."
        )
    return None


def parse_top_predictions(raw: str | None) -> list[dict]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except ValueError:
        return []
    return [item for item in value if isinstance(item, dict) and "label" in item and "confidence" in item] if isinstance(value, list) else []


@app.get("/api/crop-health/history")
def crop_history(session: Session = Depends(database.get_session)) -> list[dict]:
    rows = session.query(CropAnalysis).order_by(CropAnalysis.created_at.desc()).limit(50).all()
    return [
        {
            "id": row.id,
            "image_filename": row.image_filename,
            "disease": row.predicted_disease,
            "confidence": row.confidence,
            "status": row.status,
            "image_width": row.image_width,
            "image_height": row.image_height,
            "quality_feedback": row.quality_feedback,
            "top_predictions": parse_top_predictions(row.top_predictions),
            "created_at": iso_utc(row.created_at),
        }
        for row in rows
    ]


@app.get("/api/crop-health/model")
def crop_model_info() -> dict:
    """What the model was trained on, how it was tested, and which classes have field evidence."""
    model = crop_model.get_model()
    return {
        "status": model.status(),
        "supported_crops": SUPPORTED_CROPS,
        "low_confidence_threshold": model.threshold,
        "temperature": model.temperature,
        "card": model.card or None,
    }


# ----- fertiliser planner -------------------------------------------------------------------
@app.get("/api/fertilizer/options")
def fertilizer_options() -> dict:
    """Everything the planner form needs: reference doses, products and the rating limits, each with its source."""
    data = engine.DATA
    return {
        "references": data["references"],
        "products": data["products"],
        "units": data["units"],
        "rating_limits": data["rating_limits"],
        "split_note": data["split_note"],
        "general_sources": data["general_sources"],
        "max_dose_kg_per_hectare": engine.MAX_DOSE_KG_PER_HA,
    }


@app.post("/api/fertilizer/plan")
def fertilizer_plan(payload: PlanRequest, session: Session = Depends(database.get_session)) -> dict:
    soil = {
        key: engine.SoilInput(value=item.value, rating=item.rating)
        for key, item in (("N", payload.soil_n), ("P", payload.soil_p), ("K", payload.soil_k))
        if item is not None
    }
    label = payload.label
    sources: list[dict] = []
    if payload.dose_source == "reference":
        reference = engine.reference_by_id(payload.reference_id or "")
        assert reference is not None  # validated by PlanRequest
        n, p2o5, k2o = reference["N"], reference["P2O5"], reference["K2O"]
        label = label or f"{reference['crop']} ({reference['region']} reference dose)"
        sources.append({"title": reference["source_title"], "url": reference["source_url"], "note": reference["notes"], "verification": reference["verification"]})
        splits = payload.n_splits
    else:
        n, p2o5, k2o = payload.n or 0.0, payload.p2o5 or 0.0, payload.k2o or 0.0
        label = label or "My dose"
        splits = payload.n_splits
    try:
        plan = engine.build_plan(
            n=n, p2o5=p2o5, k2o=k2o, area_value=payload.area_value, area_unit=payload.area_unit,
            p_source=payload.p_source, k_source=payload.k_source, n_splits=splits, soil=soil,
            dose_label=label, reference_id=payload.reference_id if payload.dose_source == "reference" else None,
        )
    except engine.PlanError as exc:
        raise HTTPException(status_code=422, detail=[{"loc": ["body"], "msg": str(exc)}]) from exc
    plan["dose_source"] = payload.dose_source
    plan["sources"] = sources + engine.DATA["general_sources"]
    row = FertilizerPlan(
        label=label[:120], area_value=payload.area_value, area_unit=payload.area_unit,
        request_json=payload.model_dump_json(), result_json=json.dumps(plan),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    plan["id"] = row.id
    plan["created_at"] = iso_utc(row.created_at)
    return plan


@app.get("/api/fertilizer/history")
def fertilizer_history(session: Session = Depends(database.get_session)) -> list[dict]:
    rows = session.query(FertilizerPlan).order_by(FertilizerPlan.created_at.desc()).limit(50).all()
    out = []
    for row in rows:
        try:
            plan = json.loads(row.result_json)
        except ValueError:
            continue
        plan["id"] = row.id
        plan["created_at"] = iso_utc(row.created_at)
        out.append(plan)
    return out
