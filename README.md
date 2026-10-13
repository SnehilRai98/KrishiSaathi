# KrishiSaathi: field-tested crop screening and a fertiliser planner

Two practical tools for farmers, built to be honest about what they can and cannot tell you.

| Module | What it does | What it deliberately does not do |
| --- | --- | --- |
| **Crop health** | Screens a leaf photo against 38 disease/healthy classes across 14 crops with a model **fine-tuned on real field photos**. Shows a Grad-CAM heat-map of what the model looked at, the measured field accuracy for a score like yours, and warns when an answer was unreliable in testing. | Diagnose, or recommend pesticides or treatments. |
| **Fertilizer planner** | Turns a nutrient dose (from your Soil Health Card or a cited reference) into products, kilograms for your acres/gunthas/hectares and an application schedule, netting out the nitrogen that DAP supplies. Printable, saved history. | Decide what dose a crop needs. |

**Stack:** React 18, TypeScript, Vite, Tailwind CSS. FastAPI, SQLAlchemy, Keras/TensorFlow. SQLite by default (MySQL optional). No Docker and no external API at runtime.

## Why the crop model was retrained

The original model was trained only on clean lab photos (PlantVillage). It scored 93% on lab photos but was nearly useless on real field photos: **27% on 236 held-out PlantDoc field photos** (13% on a broader 1,080-photo sample). I fine-tuned it on field photos plus lab photos and measured it on photos it never saw:

| Held-out test | Original model | Field-tuned model |
| --- | --- | --- |
| 236 real field photos, right class | 27.1% | **75.5%** |
| Same photos, right crop | 47.0% | **85.0%** |
| 380 clean lab photos | 93.2% | 90.0% |
| 19 non-leaf photos shown as a confident result | 0% | 0% (too few to prove much) |

At the default 60% cutoff the model answers about 48% of field photos and is right 75% of the time when it answers (86% at a score of 80% or more). It is weak on some classes: for example healthy tomato leaves were recognised 1 time in 8 and tomato mosaic virus 0 in 10, so the app warns when the model gives one of the answers that was right less than half the time in testing. Full tables, per-class results and limits are in [`docs/model_report.md`](docs/model_report.md), generated from the measurements.

Limits to keep in mind: the field test set is small (margin of error about 6 points), only 27 of the 38 disease classes have any field photos (the other 11 are labelled "lab photos only" in the app), and PlantDoc photos are web-scraped, so this is a proxy for farm photos. **Do not use results to decide treatment.**

## How the fertiliser planner works

1. **Dose.** Either the dose printed on your Soil Health Card or lab report (kg/ha of N, P₂O₅, K₂O), or one of four reference doses from [`backend/fertilizer_data.json`](backend/fertilizer_data.json), each with its source: cotton irrigated 100:50:50, cotton rainfed hybrids 80:40:40 and cotton desi/hirsutum varieties 50:25:25 (Maharashtra State Package of Practices for Cotton), and irrigated wheat 120:60:40 (MPKV Rahuri; only partly verified because the source text could be read only in part). Other crops were not added because I could not verify a source. Add crops by extending that file, with a source.
2. **Arithmetic.** Product quantities from standard grades (urea 46% N, DAP 18-46-0, SSP 16% P₂O₅, MOP 60% K₂O, SOP 50% K₂O; always use the grade on your bag). Area is converted from acres, gunthas (40 per acre) or hectares. DAP's nitrogen is deducted from urea; if DAP alone over-supplies nitrogen the plan says so. Phosphorus and potassium go on at sowing; nitrogen is split into the number of parts you choose (the first part with the basal dose).
3. **Soil ratings (optional).** Low/medium/high from default limits (N 280/560, P 10/25, K 120/280 kg/ha) or from the rating printed on your report, which wins. Limits differ between states and labs, so the app shows the source and that caveat. A reference dose gets a warning when your soil rating is not medium.

Tests check the arithmetic independently: for many combinations of dose, products and splits, the products and schedule must deliver exactly the requested nutrients.

Not included: choosing a dose from soil values, crop-specific split timing, organic sources, prices.

## Folder structure

```
KrishiSaathi/
├── backend/
│   ├── main.py                 FastAPI routes, upload checks, error handlers
│   ├── crop_model.py           model loading, calibration, Grad-CAM
│   ├── fertilizer_engine.py    the planner arithmetic (pure functions)
│   ├── fertilizer_data.json    products, rating limits, reference doses and their sources
│   ├── schemas.py, config.py   request validation, optional settings
│   ├── database.py             SQLAlchemy models, in-place migrations
│   ├── models/                 field model, model_card.json, class_names.json, original lab model
│   ├── training/               train_field_model.py, evaluate_field_model.py, make_report.py, README
│   ├── scripts/check_crop_model.py   lab-photo sanity check of class order
│   └── tests/                  pytest suite
├── Frontend/src/               pages, components, lib, tests
├── docs/model_report.md        measured model results (generated)
├── run_all.bat / run_all.sh    start both servers
└── .github/workflows/ci.yml
```

## Run locally on Windows

**Prerequisites:** Python 3.10 to 3.13 and Node.js 18 or newer on your `PATH`. No database server is needed. The first install downloads TensorFlow, so allow a few minutes.

```bat
run_all.bat
```

It creates `backend\.venv`, installs dependencies and opens two windows (API and frontend). Then open <http://localhost:8080>; API docs are at <http://127.0.0.1:8000/docs>.

Manual setup:

```bat
:: Terminal 1: backend
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

:: Terminal 2: frontend
cd Frontend
npm install
npm run dev
```

Linux/macOS: `./run_all.sh`. The Windows steps follow the repository's existing `run_all.bat` and were not run on Windows while preparing this version.

### Environment variables (all optional; copy `backend\.env.example` to `backend\.env`)

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | SQLite file `backend/krishisaathi.db` | Or `mysql+pymysql://USER:PASSWORD@localhost:3306/krishisaathi`. |
| `CORS_ORIGINS` | localhost/127.0.0.1 on ports 8080 and 5173 | Browser origins allowed to call the API. |
| `MAX_UPLOAD_MB` | `10` | Largest accepted leaf photo (1 to 50). |
| `NPK_MAX_VALUE` | `10000` | Typo guard for soil-test values (kg/ha). |
| `CROP_MODEL_PATH`, `CROP_CLASS_NAMES_PATH` | files in `backend/models/` | Use a different model or label list. |

The frontend reads `VITE_API_URL` (default `http://127.0.0.1:8000`); see `Frontend/.env.example`.

## API

| Method and path | Description |
| --- | --- |
| `GET /api/health` | Database and model status. |
| `POST /api/crop-health/predict` | Multipart field `image` (JPG, PNG or WebP). Add `?explain=true` for a Grad-CAM heat-map (JPEG data URL). Returns status, disease, score, closest matches, evidence level, measured reliability for the score, guidance. |
| `GET /api/crop-health/history` | Last 50 uploads with closest matches. |
| `GET /api/crop-health/model` | Model status and the measured results from the model card. |
| `GET /api/fertilizer/options` | Reference doses, product grades, rating limits, each with sources. |
| `POST /api/fertilizer/plan` | Calculates and saves a plan. JSON: `dose_source` (`own` or `reference`), `n`/`p2o5`/`k2o` (kg/ha) or `reference_id`, `area_value`, `area_unit` (`acre`/`hectare`/`guntha`), `p_source`, `k_source`, `n_splits`, optional `soil_n`/`soil_p`/`soil_k`. |
| `GET /api/fertilizer/history` | Saved plans. |

Errors are JSON `{"detail": ...}`: 400 bad file, 413 too large, 422 invalid input, 500 generic (details go to the server log only).

## Retraining and evaluating the model

See [`backend/training/README.md`](backend/training/README.md) for data sources, the method (frozen lower network, cached augmented views, top blocks trained on one CPU core, calibration on a validation split) and the exact commands. `evaluate_field_model.py` writes `models/model_card.json`, and `make_report.py` regenerates `docs/model_report.md`. Check the PlantDoc and PlantVillage dataset licences before redistributing a model trained on them.

## Testing

```bat
cd backend
python -m pytest -q
cd ..\Frontend
npm run lint
npm run typecheck
npm test
npm run build
```

One backend test loads the real model and is skipped when TensorFlow is not installed.

## Known limitations and future work

- Crop model: 55.5% field accuracy is better than before but still modest; it should be treated as a screening hint. More field photos (especially from Indian farms and crops such as soybean, cotton, onion and sugarcane, which the model does not cover) would help most. Out-of-distribution detection is not solved: the non-leaf test is tiny.
- Planner: only four verified reference doses; no dose derivation from soil values; split timing is generic.
- No authentication: history is shared by everyone who can reach the API, so deploy only on a trusted network.
- Databases created by earlier versions keep their old `government_schemes` and `fertilizer_recommendations` tables untouched; the app no longer reads them.
- The earlier Government Schemes module was removed on request.
=======
# KrishiSaathi
AI-powered farming assistant for agricultural information and crop-related guidance.
>>>>>>> 7090b8d519e227d0aec7d4fd9580aadd9dc3e32c
