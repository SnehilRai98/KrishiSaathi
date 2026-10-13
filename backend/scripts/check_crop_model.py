"""Sanity-check the crop model's class order and behaviour with labelled leaf photos.

Download a PlantVillage-style dataset (one sub-folder per class, e.g. ``raw/color`` from
https://github.com/spMohanty/PlantVillage-Dataset) and run, from the ``backend`` folder:

    python scripts/check_crop_model.py /path/to/raw/color --per-class 10
    python scripts/check_crop_model.py /path/to/raw/color --per-class 10 --negatives
    python scripts/check_crop_model.py /path/to/raw/color --markdown ../docs/model_check.md

What the output means
---------------------
* Every class folder name must appear in ``models/class_names.json``. A wrong label order
  would give near-zero agreement, so high agreement confirms the index mapping.
* The agreement figure is **not** a field accuracy: PlantVillage photos are clean single
  leaves, and the model may have seen these exact files in training.
* The confidence summary shows how often *wrong* answers still score above the 60 %
  "low confidence" threshold, i.e. how much the threshold can and cannot protect users.
* ``--negatives`` feeds synthetic non-leaf images (flat colours, noise, gradients). These are
  weak stand-ins for real "unrelated photos"; test real ones before drawing conclusions.
"""

import argparse
import random
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import crop_model  # noqa: E402

EXTENSIONS = {".jpg", ".jpeg", ".png"}


def synthetic_negatives() -> dict[str, Image.Image]:
    rng = np.random.default_rng(0)
    size = (256, 256)
    gradient = np.tile(np.linspace(0, 255, 256, dtype=np.uint8), (256, 1))
    checker = (np.indices(size).sum(axis=0) // 32 % 2 * 255).astype(np.uint8)
    return {
        "flat grey": Image.new("RGB", size, (128, 128, 128)),
        "flat white": Image.new("RGB", size, (255, 255, 255)),
        "flat black": Image.new("RGB", size, (0, 0, 0)),
        "flat green": Image.new("RGB", size, (40, 150, 60)),
        "random noise": Image.fromarray(rng.integers(0, 255, (256, 256, 3), dtype=np.uint8)),
        "horizontal gradient": Image.fromarray(np.stack([gradient] * 3, axis=-1)),
        "checkerboard": Image.fromarray(np.stack([checker] * 3, axis=-1)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dataset", type=Path, help="folder with one sub-folder of images per class")
    parser.add_argument("--per-class", type=int, default=8, help="images sampled per class (default 8)")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--negatives", action="store_true", help="also run synthetic non-leaf images")
    parser.add_argument("--markdown", type=Path, help="write the results to this Markdown file")
    args = parser.parse_args()

    model = crop_model.CropModel()
    if not model.load():
        print("Model not available:", model.status()["error"])
        return 2
    names = set(model._class_names)

    folders = sorted(p for p in args.dataset.iterdir() if p.is_dir())
    unknown = [p.name for p in folders if p.name not in names]
    if unknown:
        print("Folders not listed in class_names.json:", *unknown, sep="\n  ")
        return 1

    threshold = crop_model.LOW_CONFIDENCE_THRESHOLD
    rng = random.Random(args.seed)
    per_class: list[tuple[str, int, int]] = []
    wrong_labels = defaultdict(set)
    ok_conf: list[float] = []
    bad_conf: list[float] = []
    for folder in folders:
        files = sorted(p for p in folder.iterdir() if p.suffix.lower() in EXTENSIONS)
        sample = rng.sample(files, min(args.per_class, len(files)))
        hits = 0
        for path in sample:
            with Image.open(path) as image:
                result = model.predict(image)
            if result.label == folder.name:
                hits += 1
                ok_conf.append(result.confidence)
            else:
                bad_conf.append(result.confidence)
                wrong_labels[folder.name].add(result.label)
        per_class.append((folder.name, hits, len(sample)))
        print(f"{hits:2d}/{len(sample):<2d}  {folder.name}")

    correct = sum(h for _, h, _ in per_class)
    total = sum(n for _, _, n in per_class)
    lines = [f"Overall agreement with folder label: {correct}/{total} = {correct / max(total, 1):.1%}"]
    lines.append(f"Classes tested: {len(per_class)} (Background_without_leaves is not in PlantVillage, so it is untested here)")
    if ok_conf:
        lines.append(f"Mean score when right: {np.mean(ok_conf):.3f}; below {threshold:.0%}: {sum(c < threshold for c in ok_conf)}/{len(ok_conf)}")
    if bad_conf:
        high = sum(c >= threshold for c in bad_conf)
        lines.append(
            f"Mean score when wrong: {np.mean(bad_conf):.3f}; wrong answers still scoring >= {threshold:.0%}: {high}/{len(bad_conf)}"
        )
    print("\n" + "\n".join(lines))
    for actual, guesses in wrong_labels.items():
        print(f"  {actual} was also predicted as: {sorted(guesses)}")

    negative_rows: list[str] = []
    if args.negatives:
        print("\nSynthetic non-leaf images:")
        for name, image in synthetic_negatives().items():
            result = model.predict(image)
            row = f"{name}: {result.label} ({result.confidence:.1%}){'  <- would be shown as a result' if not result.is_background and result.confidence >= threshold else ''}"
            negative_rows.append(row)
            print("  " + row)

    if args.markdown:
        body = ["# Crop model check (generated by scripts/check_crop_model.py)", "", *[f"- {line}" for line in lines], ""]
        body += ["| Class folder | Agreed | Sampled |", "| --- | --- | --- |"]
        body += [f"| {name} | {h} | {n} |" for name, h, n in per_class]
        if negative_rows:
            body += ["", "## Synthetic non-leaf images", "", *[f"- {row}" for row in negative_rows]]
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text("\n".join(body) + "\n", encoding="utf-8")
        print(f"\nWrote {args.markdown}")
    return 0 if total and correct / total >= 0.8 else 1


if __name__ == "__main__":
    sys.exit(main())
