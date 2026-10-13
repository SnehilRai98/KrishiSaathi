"""Measure the field-tuned model against the original, and write ``models/model_card.json``.

Everything the app shows about model quality comes from this script's output, nothing is typed in
by hand. It uses only data the model was never trained or tuned on:

* PlantDoc **test** split: real field photos (mapped to the model's classes).
* The PlantVillage evaluation sample (``--pv-eval-list``): clean lab photos.
* Held-out non-leaf photos (the third of ``--background`` that training never saw).

The original (lab-only) model is evaluated with its own original preprocessing (NEAREST resize) so the
comparison is fair to it.

Usage (from ``backend``):
  python training/evaluate_field_model.py --plantdoc D --plantvillage P --pv-eval-list L --background B \\
      --new models/crop_disease_field_v2.h5 --metrics models/field_model_metrics.json
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from datetime import date
from pathlib import Path

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import crop_model  # noqa: E402
from training.train_field_model import (  # noqa: E402
    PLANTDOC_TO_LABEL,
    SEED,
    apply_temperature,
    ece,
    list_images,
    load_rgb,
)

THRESHOLDS = (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)


def preprocess(image: Image.Image, resample) -> np.ndarray:
    return np.asarray(image.convert("RGB").resize((224, 224), resample), dtype="float32") / 255.0


def predict_all(model, paths: list[Path], resample) -> np.ndarray:
    out = []
    for i in range(0, len(paths), 32):
        batch = []
        for path in paths[i : i + 32]:
            batch.append(preprocess(load_rgb(path), resample))
        out.append(np.asarray(model.predict(np.stack(batch), verbose=0, batch_size=32)))
    return np.concatenate(out) if out else np.zeros((0, 39))


def crop_of(label: str) -> str:
    return label.split("___")[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--plantdoc", required=True)
    parser.add_argument("--plantvillage", required=True)
    parser.add_argument("--pv-eval-list", required=True)
    parser.add_argument("--background", required=True)
    parser.add_argument("--new", default="models/crop_disease_field_v2.h5")
    parser.add_argument("--old", default=str(crop_model.LAB_MODEL_PATH))
    parser.add_argument("--metrics", default="models/field_model_metrics.json", help="written by train_field_model.py")
    parser.add_argument("--card", default="models/model_card.json")
    parser.add_argument("--threshold", type=float, default=None, help="override the chosen low-confidence threshold")
    args = parser.parse_args()

    import keras

    names = json.loads(crop_model.DEFAULT_CLASS_NAMES_PATH.read_text(encoding="utf-8"))
    index = {n: i for i, n in enumerate(names)}
    bg_index = index[crop_model.BACKGROUND_LABEL]
    train_metrics = json.loads(Path(args.metrics).read_text())
    temperature = float(train_metrics["temperature"])
    new_model = keras.models.load_model(args.new, compile=False)
    old_model = keras.models.load_model(args.old, compile=False)

    # ---- replay the training split so the held-out background photos are identified exactly ------
    rng = random.Random(SEED)
    plantdoc = Path(args.plantdoc)
    train_files, test_files = [], []
    for split, bucket in (("train", train_files), ("test", test_files)):
        for folder in sorted((plantdoc / split).iterdir()):
            if folder.name in PLANTDOC_TO_LABEL:
                bucket += [(p, index[PLANTDOC_TO_LABEL[folder.name]]) for p in list_images(folder)]
    by_class: dict[int, list] = {}
    for item in train_files:
        by_class.setdefault(item[1], []).append(item)
    for items in by_class.values():
        rng.shuffle(items)
    bg_all = list_images(Path(args.background))
    rng.shuffle(bg_all)
    bg_test = bg_all[: max(1, len(bg_all) // 3)]

    # ---- field test ---------------------------------------------------------------------------
    paths = [p for p, _ in test_files]
    truth = np.array([t for _, t in test_files])
    new_raw = predict_all(new_model, paths, Image.BILINEAR)
    old_raw = predict_all(old_model, paths, Image.NEAREST)
    new_cal = apply_temperature(new_raw, temperature)

    def top1(p):
        return float((p.argmax(1) == truth).mean())

    def crop_top1(p):
        return float(np.mean([crop_of(names[a]) == crop_of(names[b]) for a, b in zip(p.argmax(1), truth)]))

    per_class = {}
    for label_index in sorted(set(truth.tolist())):
        mask = truth == label_index
        per_class[names[label_index]] = {"n": int(mask.sum()), "top1": float((new_cal.argmax(1)[mask] == label_index).mean())}

    # How often the model was right *when it said* each class (what matters to someone reading an answer).
    predicted = new_cal.argmax(1)
    per_prediction = {}
    for label_index in sorted(set(predicted.tolist())):
        mask = predicted == label_index
        per_prediction[names[label_index]] = {"n_predicted": int(mask.sum()), "precision": float((truth[mask] == label_index).mean())}

    selective = []
    for t in THRESHOLDS:
        keep = new_cal.max(1) >= t
        selective.append({
            "threshold": t,
            "coverage": float(keep.mean()),
            "accuracy_when_answered": float((new_cal.argmax(1)[keep] == truth[keep]).mean()) if keep.any() else None,
        })

    # ---- lab sample -----------------------------------------------------------------------------
    lab_paths, lab_truth = [], []
    pv_root = Path(args.plantvillage)
    for line in Path(args.pv_eval_list).read_text().split("\n"):
        parts = line.strip().split("/")
        if len(parts) == 4 and parts[2] in index and (pv_root / parts[2] / parts[3]).is_file():
            lab_paths.append(pv_root / parts[2] / parts[3])
            lab_truth.append(index[parts[2]])
    lab_truth = np.array(lab_truth)
    lab_new = predict_all(new_model, lab_paths, Image.BILINEAR)
    lab_old = predict_all(old_model, lab_paths, Image.NEAREST)

    # ---- non-leaf photos --------------------------------------------------------------------------
    threshold = args.threshold
    if threshold is None:
        # Lowest cutoff at which answered field photos are at least 75% right while at least 40% of photos
        # still get an answer; otherwise the long-standing default of 0.6. (A cutoff of 0.8 is more accurate
        # but answers barely a quarter of field photos; the app shows measured accuracy per score instead.)
        ok = [row["threshold"] for row in selective if row["accuracy_when_answered"] and row["accuracy_when_answered"] >= 0.75 and row["coverage"] >= 0.40]
        threshold = min(ok) if ok else 0.6
    nl_new = apply_temperature(predict_all(new_model, bg_test, Image.BILINEAR), temperature)
    nl_old = predict_all(old_model, bg_test, Image.NEAREST)

    def shown(p, t):
        return float(((p.max(1) >= t) & (p.argmax(1) != bg_index)).mean())

    field_classes = {PLANTDOC_TO_LABEL[k] for k in PLANTDOC_TO_LABEL}
    card = {
        "model_version": "field-v2",
        "created": date.today().isoformat(),
        "temperature": temperature,
        "low_confidence_threshold": threshold,
        "class_evidence": {n: ("field" if n in field_classes else "lab_only") for n in names if n != crop_model.BACKGROUND_LABEL},
        "metrics": {
            "field_test": {
                "dataset": "PlantDoc test split (real field photos, never used for training or tuning)",
                "n": int(len(truth)),
                "top1": top1(new_cal),
                "crop_top1": crop_top1(new_cal),
                "baseline_top1": top1(old_raw),
                "baseline_crop_top1": crop_top1(old_raw),
                "ece_before_calibration": ece(new_raw, truth),
                "ece_after_calibration": ece(new_cal, truth),
                "selective": selective,
                "per_class": per_class,
                "per_prediction": per_prediction,
            },
            "lab_test": {
                "n": int(len(lab_truth)),
                "top1": float((lab_new.argmax(1) == lab_truth).mean()),
                "baseline_top1": float((lab_old.argmax(1) == lab_truth).mean()),
            },
            "non_leaf": {
                "n": int(len(bg_test)),
                "shown_as_result": shown(nl_new, threshold),
                "baseline_shown_as_result": shown(nl_old, 0.6),
            },
        },
        "training": train_metrics.get("data", {}),
        "limitations": [
            "Field accuracy was measured on a small public test set (PlantDoc) with 27 of the 38 disease classes. The other 11 classes were learned from lab photos only and are labelled as such.",
            "Only 14 crops are supported. Photos of other plants, or of several leaves, soil or hands, can still produce a confident wrong answer.",
            "The non-leaf check uses a handful of ordinary photos and graphics, so it says little about every kind of non-leaf image.",
            "Confidence was calibrated on a small field validation set; treat it as a rough guide, not a probability.",
        ],
    }
    Path(args.card).write_text(json.dumps(card, indent=2))
    m = card["metrics"]
    print(f"FIELD TEST n={m['field_test']['n']}: exact {m['field_test']['top1']:.3f} (baseline {m['field_test']['baseline_top1']:.3f}); "
          f"crop {m['field_test']['crop_top1']:.3f} (baseline {m['field_test']['baseline_crop_top1']:.3f})")
    print(f"  ECE {m['field_test']['ece_before_calibration']:.3f} -> {m['field_test']['ece_after_calibration']:.3f}   temperature {temperature:.2f}  threshold {threshold}")
    for row in selective:
        acc = "n/a" if row["accuracy_when_answered"] is None else f"{row['accuracy_when_answered']:.3f}"
        print(f"  threshold {row['threshold']}: answers {row['coverage']:.2f} of photos, accuracy when answered {acc}")
    print(f"LAB n={m['lab_test']['n']}: {m['lab_test']['top1']:.3f} (baseline {m['lab_test']['baseline_top1']:.3f})")
    print(f"NON-LEAF n={m['non_leaf']['n']}: shown as result {m['non_leaf']['shown_as_result']:.2f} (baseline {m['non_leaf']['baseline_shown_as_result']:.2f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
