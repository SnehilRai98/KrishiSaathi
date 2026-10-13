"""Fine-tune the crop-disease classifier so it works on real field photos.

Why this exists
---------------
The original model was trained on PlantVillage (clean lab photos). On 1,080 real field photos from
PlantDoc it agreed with the label only 13% of the time (see docs/model_report.md). This script
adapts the model to field conditions while keeping the same 39 outputs, so the API does not change.

Method (small enough for one CPU core)
--------------------------------------
1. Keep the lower network (up to ``block_12_add``) frozen. Run many *augmented* views of every
   training photo through it once and cache the result (``--cache``).
2. Train only the top (blocks 13-16, final 1x1 conv, classifier). Batch-norm statistics stay frozen.
3. Early-stop on a validation split taken from PlantDoc *train*. The official PlantDoc *test* split,
   the PlantVillage evaluation sample and held-out non-leaf photos are never used for training or
   model selection.
4. Fit one temperature on the validation split so reported confidences are better calibrated.

Data layout expected (see backend/training/README.md for download commands)
--------------------------------------------------------------------------
  --plantdoc      folder with ``train/<class>/*.jpg`` and ``test/<class>/*.jpg``
  --plantvillage  folder with ``<ClassName>/*.jpg`` (PlantVillage ``raw/color``), training sample
  --pv-eval-list  text file of PlantVillage files reserved for evaluation (excluded from training)
  --background    folder of ordinary non-leaf photos (the ``Background_without_leaves`` class)

Usage:  python training/train_field_model.py --plantdoc D --plantvillage P --pv-eval-list L --background B
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import crop_model  # noqa: E402

IMAGE = 224
SEED = 2026

# PlantDoc folder -> PlantVillage class. Every PlantDoc class used here has a direct counterpart.
PLANTDOC_TO_LABEL = {
    "Apple Scab Leaf": "Apple___Apple_scab",
    "Apple leaf": "Apple___healthy",
    "Apple rust leaf": "Apple___Cedar_apple_rust",
    "Bell_pepper leaf spot": "Pepper,_bell___Bacterial_spot",
    "Bell_pepper leaf": "Pepper,_bell___healthy",
    "Blueberry leaf": "Blueberry___healthy",
    "Cherry leaf": "Cherry_(including_sour)___healthy",
    "Corn Gray leaf spot": "Corn_(maize)___Cercospora_leaf_spot Gray_leaf_spot",
    "Corn leaf blight": "Corn_(maize)___Northern_Leaf_Blight",
    "Corn rust leaf": "Corn_(maize)___Common_rust_",
    "Peach leaf": "Peach___healthy",
    "Potato leaf early blight": "Potato___Early_blight",
    "Potato leaf late blight": "Potato___Late_blight",
    "Raspberry leaf": "Raspberry___healthy",
    "Soyabean leaf": "Soybean___healthy",
    "Squash Powdery mildew leaf": "Squash___Powdery_mildew",
    "Strawberry leaf": "Strawberry___healthy",
    "Tomato Early blight leaf": "Tomato___Early_blight",
    "Tomato Septoria leaf spot": "Tomato___Septoria_leaf_spot",
    "Tomato leaf": "Tomato___healthy",
    "Tomato leaf bacterial spot": "Tomato___Bacterial_spot",
    "Tomato leaf late blight": "Tomato___Late_blight",
    "Tomato leaf mosaic virus": "Tomato___Tomato_mosaic_virus",
    "Tomato leaf yellow virus": "Tomato___Tomato_Yellow_Leaf_Curl_Virus",
    "Tomato mold leaf": "Tomato___Leaf_Mold",
    "grape leaf": "Grape___healthy",
    "grape leaf black rot": "Grape___Black_rot",
}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


def list_images(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)


def load_rgb(path: Path) -> Image.Image:
    image = Image.open(path)
    image.draft("RGB", (IMAGE * 2, IMAGE * 2))  # fast JPEG decode for large phone photos
    return image.convert("RGB")


def clean_view(image: Image.Image) -> np.ndarray:
    return crop_model.CropModel.preprocess(image)[0]


def augmented_view(image: Image.Image, rng: random.Random) -> np.ndarray:
    """Random crop, flips, rotation, colour and blur changes that imitate phone-camera variety."""
    width, height = image.size
    area = rng.uniform(0.45, 1.0)
    ratio = rng.uniform(0.75, 1.33)
    crop_w = int(min(width, max(32, (width * height * area * ratio) ** 0.5)))
    crop_h = int(min(height, max(32, crop_w / ratio)))
    left = rng.randint(0, max(0, width - crop_w))
    top = rng.randint(0, max(0, height - crop_h))
    image = image.crop((left, top, left + crop_w, top + crop_h))
    if rng.random() < 0.5:
        image = image.transpose(Image.FLIP_LEFT_RIGHT)
    if rng.random() < 0.3:
        image = image.transpose(Image.FLIP_TOP_BOTTOM)
    image = image.rotate(rng.uniform(-30, 30), resample=Image.BILINEAR)
    image = ImageEnhance.Brightness(image).enhance(rng.uniform(0.6, 1.4))
    image = ImageEnhance.Contrast(image).enhance(rng.uniform(0.7, 1.3))
    image = ImageEnhance.Color(image).enhance(rng.uniform(0.6, 1.4))
    if rng.random() < 0.25:
        image = image.filter(ImageFilter.GaussianBlur(rng.uniform(0.3, 1.5)))
    return clean_view(image)


def synthetic_backgrounds(count: int, rng: random.Random) -> list[np.ndarray]:
    """Flat colours, gradients and noise. They teach 'no leaf here', but are weak stand-ins for real scenes."""
    out = []
    for _ in range(count):
        kind = rng.choice(["flat", "gradient", "noise", "blotch"])
        base = np.array([rng.randint(0, 255) for _ in range(3)], dtype=np.float32)
        if kind == "flat":
            arr = np.ones((IMAGE, IMAGE, 3), np.float32) * base
        elif kind == "gradient":
            other = np.array([rng.randint(0, 255) for _ in range(3)], dtype=np.float32)
            t = np.linspace(0, 1, IMAGE, dtype=np.float32)[None, :, None]
            arr = base * (1 - t) + other * t
            arr = np.broadcast_to(arr, (IMAGE, IMAGE, 3)).copy()
            if rng.random() < 0.5:
                arr = arr.transpose(1, 0, 2)
        elif kind == "noise":
            arr = np.clip(base + np.random.default_rng(rng.randint(0, 10**6)).normal(0, rng.uniform(5, 70), (IMAGE, IMAGE, 3)), 0, 255)
        else:
            small = np.random.default_rng(rng.randint(0, 10**6)).uniform(0, 255, (6, 6, 3)).astype(np.uint8)
            arr = np.asarray(Image.fromarray(small).resize((IMAGE, IMAGE), Image.BICUBIC), dtype=np.float32)
        out.append(np.clip(arr, 0, 255).astype(np.float32) / 255.0)
    return out


def build_cache(args, names: list[str], lower) -> dict:
    rng = random.Random(SEED)
    index = {name: i for i, name in enumerate(names)}
    bg_index = index[crop_model.BACKGROUND_LABEL]

    plantdoc = Path(args.plantdoc)
    train_files: list[tuple[Path, int]] = []
    test_files: list[tuple[Path, int]] = []
    for split, bucket in (("train", train_files), ("test", test_files)):
        for folder in sorted((plantdoc / split).iterdir()):
            if folder.name in PLANTDOC_TO_LABEL:
                bucket += [(p, index[PLANTDOC_TO_LABEL[folder.name]]) for p in list_images(folder)]
    # validation = 12 % of PlantDoc train, stratified, used only for early stopping and temperature fitting
    by_class: dict[int, list] = {}
    for item in train_files:
        by_class.setdefault(item[1], []).append(item)
    val_files, fit_files = [], []
    for items in by_class.values():
        rng.shuffle(items)
        cut = max(1, round(len(items) * 0.12))
        val_files += items[:cut]
        fit_files += items[cut:]

    pv_eval = set(Path(args.pv_eval_list).read_text().split("\n")) if args.pv_eval_list else set()
    pv_root = Path(args.plantvillage)
    pv_files = []
    for folder in sorted(pv_root.iterdir()):
        if folder.is_dir() and folder.name in index:
            for p in list_images(folder):
                if f"raw/color/{folder.name}/{p.name}" not in pv_eval:
                    pv_files.append((p, index[folder.name]))

    bg_all = list_images(Path(args.background))
    rng.shuffle(bg_all)
    bg_test = bg_all[: max(1, len(bg_all) // 3)]  # held out, never trained on
    bg_train = bg_all[len(bg_test):]

    def batches(arrs):
        feats = []
        for i in range(0, len(arrs), 64):
            feats.append(lower.predict(np.stack(arrs[i : i + 64]), verbose=0, batch_size=64).astype(np.float16))
        return np.concatenate(feats) if feats else np.zeros((0, 14, 14, 96), np.float16)

    def encode(files, views, clean_first=True, tag=""):
        feats, labels, t0 = [], [], time.time()
        for n, (path, label) in enumerate(files):
            try:
                image = load_rgb(path)
            except Exception:  # noqa: BLE001 - skip unreadable files
                continue
            arrs = [clean_view(image)] if clean_first else []
            arrs += [augmented_view(image, rng) for _ in range(views - len(arrs))]
            feats.append(batches(arrs))
            labels += [label] * len(arrs)
            if (n + 1) % 200 == 0:
                print(f"  {tag}: {n + 1}/{len(files)} photos, {time.time() - t0:.0f}s", flush=True)
        return np.concatenate(feats), np.array(labels)

    # Each stage is saved as soon as it is done, so an interrupted run resumes instead of starting over.
    parts_dir = Path(args.cache).with_suffix("")
    parts_dir.mkdir(parents=True, exist_ok=True)

    def stage(name: str, build):
        path = parts_dir / f"{name}.npz"
        if path.exists():
            print(f"  {name}: loaded from checkpoint", flush=True)
            loaded = np.load(path)
            return loaded["x"], loaded["y"]
        x, y = build()
        np.savez(path, x=x, y=y)
        return x, y

    print("encoding PlantDoc train views...", flush=True)
    x1, y1 = stage("plantdoc_train", lambda: encode(fit_files, args.views_field, tag="plantdoc"))
    print("encoding PlantVillage views...", flush=True)
    x2, y2 = stage("plantvillage_train", lambda: encode(pv_files, args.views_lab, tag="plantvillage"))
    print("encoding background views...", flush=True)
    xb, yb = stage("background_train", lambda: encode([(p, bg_index) for p in bg_train], 8, tag="background"))
    xs, ys = stage("synthetic", lambda: (batches(synthetic_backgrounds(args.synthetic, rng)), np.full(args.synthetic, bg_index)))
    print("encoding validation/test...", flush=True)
    xv, yv = stage("plantdoc_val", lambda: encode(val_files, 1, tag="val"))
    xt, yt = stage("plantdoc_test", lambda: encode(test_files, 1, tag="test"))
    xbt, ybt = stage("background_test", lambda: encode([(p, bg_index) for p in bg_test], 1, tag="bg-test"))

    domain = np.concatenate([np.zeros(len(y1)), np.ones(len(y2)), np.full(len(yb) + len(ys), 2)])
    return dict(
        x=np.concatenate([x1, x2, xb, xs]), y=np.concatenate([y1, y2, yb, ys]), domain=domain,
        xv=xv, yv=yv, xt=xt, yt=yt, xbt=xbt, ybt=ybt,
        counts=dict(plantdoc_train_photos=len(fit_files), plantdoc_val_photos=len(val_files), plantdoc_test_photos=len(test_files),
                    plantvillage_train_photos=len(pv_files), background_train_photos=len(bg_train), background_test_photos=len(bg_test),
                    synthetic_backgrounds=int(args.synthetic)),
    )


def ece(probs: np.ndarray, truth: np.ndarray, bins: int = 15) -> float:
    conf = probs.max(1)
    hit = probs.argmax(1) == truth
    edges = np.linspace(0, 1, bins + 1)
    total = 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (conf > lo) & (conf <= hi)
        if mask.any():
            total += mask.mean() * abs(hit[mask].mean() - conf[mask].mean())
    return float(total)


def apply_temperature(probs: np.ndarray, temperature: float) -> np.ndarray:
    logits = np.log(np.clip(probs, 1e-12, 1)) / temperature
    logits -= logits.max(1, keepdims=True)
    exp = np.exp(logits)
    return exp / exp.sum(1, keepdims=True)


def fit_temperature(probs: np.ndarray, truth: np.ndarray) -> float:
    best, best_nll = 1.0, float("inf")
    for t in np.arange(0.5, 6.01, 0.05):
        p = apply_temperature(probs, float(t))
        nll = -np.log(np.clip(p[np.arange(len(truth)), truth], 1e-12, 1)).mean()
        if nll < best_nll:
            best, best_nll = float(t), nll
    return best


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--plantdoc", required=True)
    parser.add_argument("--plantvillage", required=True)
    parser.add_argument("--pv-eval-list", default="")
    parser.add_argument("--background", required=True)
    parser.add_argument("--cache", default="training_cache.npz", help="where the cached features are stored")
    parser.add_argument("--out", default="models/crop_disease_field_v2.h5")
    parser.add_argument("--views-field", type=int, default=3, help="views per PlantDoc training photo")
    parser.add_argument("--views-lab", type=int, default=2, help="views per PlantVillage training photo")
    parser.add_argument("--synthetic", type=int, default=150)
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--report", default="models/field_model_metrics.json")
    args = parser.parse_args()

    import tensorflow as tf

    tf.random.set_seed(SEED)
    np.random.seed(SEED)
    model = crop_model.CropModel()
    if not model.load():
        print("Cannot load the starting model:", model.status()["error"])
        return 2
    base = model._model
    names = model._class_names
    cut = base.get_layer("block_12_add").output
    lower = tf.keras.Model(base.input, cut)
    top = tf.keras.Model(cut, base.output)

    cache_path = Path(args.cache)
    if cache_path.exists():
        print("using cached features", cache_path)
        data = dict(np.load(cache_path, allow_pickle=True))
        data["counts"] = data["counts"].item()
    else:
        data = build_cache(args, names, lower)
        np.savez(cache_path, **data)

    # ---- baseline numbers from the starting weights (same cached features) -------------------
    x, y, domain = data["x"], data["y"], data["domain"]
    xv, yv, xt, yt = data["xv"], data["yv"], data["xt"], data["yt"]
    start_test = top.predict(xt.astype("float32"), verbose=0, batch_size=64)
    print(f"starting weights on PlantDoc test (new preprocessing): {(start_test.argmax(1) == yt).mean():.3f}")

    # ---- unfreeze the top, keep batch-norm frozen ---------------------------------------------
    for layer in top.layers:
        if layer.weights:
            layer.trainable = not isinstance(layer, tf.keras.layers.BatchNormalization)
    counts = np.bincount(y.astype(int), minlength=len(names)).astype(np.float64)
    weights = np.where(counts > 0, (counts.max() / np.maximum(counts, 1)) ** 0.5, 1.0)
    weights = np.clip(weights, 1.0, 8.0)
    sample_weight = weights[y.astype(int)] * np.where(domain == 0, 1.5, 1.0)  # field photos matter most
    onehot = tf.one_hot(y.astype(int), len(names)).numpy()
    top.compile(
        optimizer=tf.keras.optimizers.Adam(tf.keras.optimizers.schedules.CosineDecay(args.lr, decay_steps=max(1, args.epochs * (len(y) // 32)))),
        loss=tf.keras.losses.CategoricalCrossentropy(label_smoothing=0.1),
    )

    best_acc, best_weights, bad, history = -1.0, None, 0, []
    for epoch in range(1, args.epochs + 1):
        started = time.time()
        order = np.random.permutation(len(y))
        loss = top.fit(x[order].astype("float32"), onehot[order], sample_weight=sample_weight[order], batch_size=32, epochs=1, verbose=0).history["loss"][0]
        val_acc = float((top.predict(xv.astype("float32"), verbose=0, batch_size=64).argmax(1) == yv).mean())
        history.append(dict(epoch=epoch, train_loss=float(loss), val_accuracy=val_acc))
        print(f"epoch {epoch:2d}  loss {loss:.3f}  field-val acc {val_acc:.3f}  ({time.time() - started:.0f}s)", flush=True)
        if val_acc > best_acc:
            best_acc, best_weights, bad = val_acc, top.get_weights(), 0
        else:
            bad += 1
            if bad >= 3:
                print("early stop")
                break
    top.set_weights(best_weights)

    # ---- temperature on validation, metrics on untouched test sets ----------------------------
    pv_val = top.predict(xv.astype("float32"), verbose=0, batch_size=64)
    temperature = fit_temperature(pv_val, yv)
    test_probs = top.predict(xt.astype("float32"), verbose=0, batch_size=64)
    calibrated = apply_temperature(test_probs, temperature)
    metrics = dict(
        data=data["counts"], epochs_run=len(history), history=history, temperature=temperature,
        plantdoc_test=dict(
            accuracy=float((test_probs.argmax(1) == yt).mean()),
            ece_before=ece(test_probs, yt), ece_after=ece(calibrated, yt), n=int(len(yt)),
        ),
    )
    print(json.dumps(metrics["plantdoc_test"], indent=2))
    Path(args.report).write_text(json.dumps(metrics, indent=2))
    base.save(args.out)
    print("saved", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
