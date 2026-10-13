# Training and evaluating the field-tuned crop model

The shipped model (`models/crop_disease_field_v2.h5`) was produced by these two scripts. Everything the app
reports about its quality comes from `evaluate_field_model.py`; nothing is typed in by hand.

## Why it was retrained

The original PlantVillage-only model agreed with the label on 93% of clean lab photos but only **13%** of
1,080 real field photos from PlantDoc (29.8% for the right crop). It was not usable in a real field.

## Data (all public)

| Data | Source | Used for |
| --- | --- | --- |
| PlantDoc train | <https://github.com/pratikkayal/PlantDoc-Dataset> `train/` | training (88%) and validation (12%) |
| PlantDoc test | same repo, `test/` | **final field evaluation only** |
| PlantVillage | <https://github.com/spMohanty/PlantVillage-Dataset> `raw/color/` | 40 photos per class for training; a different 10 per class (380) for evaluation |
| Non-leaf photos | OpenCV sample images (`samples/data`) | `Background_without_leaves` class; one third held out for evaluation |

Download only what you need with a partial clone (the repositories are large):

```bash
git clone --depth 1 --filter=blob:none --no-checkout https://github.com/pratikkayal/PlantDoc-Dataset.git plantdoc
cd plantdoc && git checkout HEAD -- train test
```

The PlantDoc folders are mapped to the model's existing class names in `PLANTDOC_TO_LABEL`
(27 of the 38 disease classes have field photos; the other 11 stay lab-only and are labelled that way in the app).

## Method

1. Freeze the network up to `block_12_add`, run many augmented views of each photo through it once and cache the result
   (this keeps training feasible on one CPU core).
2. Train only the top blocks and the classifier (batch-norm statistics frozen), with label smoothing, class weighting and
   extra weight on field photos. Stop early on the PlantDoc validation split.
3. Fit one temperature on the validation split (confidence calibration).
4. Evaluate on the held-out sets and write `models/model_card.json`.

```bash
cd backend
python training/train_field_model.py --plantdoc PD --plantvillage PV/raw/color \
    --pv-eval-list pv_eval.txt --background nonleaf_photos
python training/evaluate_field_model.py --plantdoc PD --plantvillage PV/raw/color \
    --pv-eval-list pv_eval.txt --background nonleaf_photos
```

`pv_eval.txt` lists the PlantVillage files reserved for evaluation (`raw/color/<Class>/<file>`, one per line);
training excludes them.

## Honest limits

- The field test set is small (a few hundred photos) so differences of a few percentage points are noise.
- PlantDoc contains only 27 of the 38 disease classes, and photos are web-scraped, so it is a proxy for farm photos, not a substitute.
- Preprocessing now uses an antialiased bilinear resize; the original model used nearest-neighbour. Both are evaluated with their own.
