# Model files

| File | Used by the app? | Notes |
| ---- | ---------------- | ----- |
| `crop_disease_field_v2.h5` | **Yes** (default) | MobileNetV2 leaf-disease classifier fine-tuned on real field photos. Input 224x224 RGB scaled to 0-1 (bilinear resize), 39 softmax outputs. Trained with `../training/train_field_model.py`. |
| `model_card.json` | **Yes** | Written by `../training/evaluate_field_model.py`: calibration temperature, answer cutoff, per-class evidence (field vs lab-only) and the measured test results the app displays. Delete it and the app falls back to neutral defaults and says no evaluation exists. |
| `field_model_metrics.json` | No | Training log and the fitted temperature (input to the evaluation script). |
| `class_names.json` | **Yes** | The 39 labels in output order (alphabetical PlantVillage folder names, `Background_without_leaves` at index 4). |
| `crop_disease_mobilenetv2_final.h5` | Fallback | The original PlantVillage-only (lab) model. Used only if the field model is missing, or by setting `CROP_MODEL_PATH`. It uses a nearest-neighbour resize and has no model card. It scored 27.1% on the field test set. |
| `crop_disease_mobilenetv2.h5` | No | Best-validation checkpoint from the original training run; kept as a backup. |
| `classifier.pkl`, `fertilizer.pkl`, `ferti_recommendation.ipynb`, `fertilizer_test.ipynb` | No | Earlier fertilizer-classifier experiment. Its training CSV is not in the repository, so it cannot be validated and the app does not use it. **Never unpickle files from sources you do not trust.** |

The measured quality of the field model is in `../../docs/model_report.md`.
