"""Turn a nutrient dose into a fertiliser plan: products, quantities, area and application splits.

This module only does arithmetic on numbers the farmer supplies (or on a cited reference dose).
It never decides what dose a crop needs. All constants live in ``fertilizer_data.json`` together
with their sources.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

DATA_PATH = Path(__file__).parent / "fertilizer_data.json"
DATA: dict = json.loads(DATA_PATH.read_text(encoding="utf-8"))

AreaUnit = Literal["acre", "hectare", "guntha"]
PSource = Literal["dap", "ssp"]
KSource = Literal["mop", "sop"]
Rating = Literal["low", "medium", "high"]

MAX_DOSE_KG_PER_HA = 600.0  # typo guard per nutrient, not an agronomic limit
MIN_AREA_HA = 0.001
MAX_AREA_HA = 4000.0


class PlanError(ValueError):
    """The request cannot be turned into a plan (message is safe to show to the user)."""


def reference_by_id(reference_id: str) -> dict | None:
    return next((item for item in DATA["references"] if item["id"] == reference_id), None)


def to_hectares(value: float, unit: AreaUnit) -> float:
    per_acre = DATA["units"]["hectare_per_acre"]
    if unit == "hectare":
        return value
    if unit == "acre":
        return value * per_acre
    if unit == "guntha":
        return value * per_acre / DATA["units"]["gunthas_per_acre"]
    raise PlanError("Unknown area unit.")


def rate_nutrient(nutrient: Literal["N", "P", "K"], value: float) -> Rating:
    """Low / medium / high using the limits in fertilizer_data.json (boundaries count as medium)."""
    limits = DATA["rating_limits"][nutrient]
    if value < limits["low_below"]:
        return "low"
    if value > limits["high_above"]:
        return "high"
    return "medium"


@dataclass
class SoilInput:
    value: float | None = None
    rating: Rating | None = None


def interpret_soil(soil: dict[str, SoilInput]) -> list[dict]:
    """Per-nutrient rating. A rating printed on the farmer's card wins over a computed one."""
    out = []
    labels = {"N": "Nitrogen", "P": "Phosphorus", "K": "Potassium"}
    for key in ("N", "P", "K"):
        item = soil.get(key) or SoilInput()
        if item.rating:
            out.append({"nutrient": key, "label": labels[key], "rating": item.rating, "value": item.value, "basis": "from your report"})
        elif item.value is not None:
            out.append({"nutrient": key, "label": labels[key], "rating": rate_nutrient(key, item.value), "value": item.value, "basis": "computed with default limits"})
    return out


def _round(value: float, digits: int = 1) -> float:
    return round(value + 1e-9, digits)


def build_plan(
    *,
    n: float,
    p2o5: float,
    k2o: float,
    area_value: float,
    area_unit: AreaUnit,
    p_source: PSource = "dap",
    k_source: KSource = "mop",
    n_splits: int = 2,
    soil: dict[str, SoilInput] | None = None,
    dose_label: str = "",
    reference_id: str | None = None,
) -> dict:
    """Compute the plan. ``n``, ``p2o5`` and ``k2o`` are nutrient doses in kg per hectare."""
    for name, value in (("Nitrogen", n), ("Phosphorus (P2O5)", p2o5), ("Potassium (K2O)", k2o)):
        if value < 0 or value > MAX_DOSE_KG_PER_HA:
            raise PlanError(f"{name} dose must be between 0 and {MAX_DOSE_KG_PER_HA:g} kg per hectare.")
    if n + p2o5 + k2o <= 0:
        raise PlanError("Enter a dose for at least one nutrient.")
    if not 1 <= n_splits <= 4:
        raise PlanError("Nitrogen can be split into 1 to 4 parts.")
    area_ha = to_hectares(area_value, area_unit)
    if not MIN_AREA_HA <= area_ha <= MAX_AREA_HA:
        raise PlanError("Area is outside the supported range.")

    products = DATA["products"]
    warnings: list[str] = []

    # ---- phosphorus first, because DAP also carries nitrogen -----------------------------------
    p_kg_ha = (p2o5 / (products[p_source]["P2O5"] / 100)) if p2o5 > 0 else 0.0
    n_from_p_ha = p_kg_ha * products[p_source]["N"] / 100
    k_kg_ha = (k2o / (products[k_source]["K2O"] / 100)) if k2o > 0 else 0.0

    # ---- nitrogen splits, netting out the nitrogen already supplied by DAP ----------------------
    per_split = [n / n_splits] * n_splits
    credit = n_from_p_ha
    for i in range(n_splits):
        take = min(per_split[i], credit)
        per_split[i] -= take
        credit -= take
    if credit > 1e-9:
        extra = _round(credit)
        warnings.append(
            f"The DAP needed for your phosphorus dose already supplies about {_round(n_from_p_ha)} kg N per hectare, which is {extra} kg more than your nitrogen dose. "
            "Consider SSP as the phosphorus source, or check the dose with your agriculture officer."
        )
    urea_split_ha = [x / (products["urea"]["N"] / 100) for x in per_split]
    urea_ha = sum(urea_split_ha)

    def scale(kg_ha: float) -> float:
        return kg_ha * area_ha

    applications = []
    for i in range(n_splits):
        items = []
        if i == 0:
            if p_kg_ha:
                items.append({"product": products[p_source]["name"], "key": p_source, "kg": _round(scale(p_kg_ha))})
            if k_kg_ha:
                items.append({"product": products[k_source]["name"], "key": k_source, "kg": _round(scale(k_kg_ha))})
        if urea_split_ha[i] > 1e-9:
            items.append({"product": products["urea"]["name"], "key": "urea", "kg": _round(scale(urea_split_ha[i]))})
        stage = "Basal (at sowing or planting)" if i == 0 else f"Top-dress {i} of {n_splits - 1}"
        applications.append({"stage": stage, "items": items})

    totals = []
    for key, kg_ha in (("urea", urea_ha), (p_source, p_kg_ha), (k_source, k_kg_ha)):
        if kg_ha > 1e-9:
            totals.append(
                {
                    "key": key,
                    "product": products[key]["name"],
                    "grade": {"N": products[key]["N"], "P2O5": products[key]["P2O5"], "K2O": products[key]["K2O"]},
                    "kg_per_hectare": _round(kg_ha),
                    "kg_for_area": _round(scale(kg_ha)),
                }
            )

    soil_ratings = interpret_soil(soil or {})
    if soil_ratings and reference_id:
        notes_for = [f"{r['label']} is rated {r['rating']}" for r in soil_ratings if r["rating"] != "medium"]
        if notes_for:
            warnings.append(
                "A reference dose is a general starting point, not tuned to your field. Your soil test shows: " + "; ".join(notes_for) + ". "
                "Prefer the dose printed on your own Soil Health Card or lab report for this field."
            )
    if p2o5 > 0 and n_splits == 1 and n > 0:
        warnings.append("All the nitrogen is applied at once. Splitting it usually reduces losses; follow your crop's package of practice.")

    return {
        "label": dose_label,
        "reference_id": reference_id,
        "area": {"value": area_value, "unit": area_unit, "hectares": round(area_ha, 4), "acres": round(area_ha / DATA["units"]["hectare_per_acre"], 3)},
        "dose_kg_per_hectare": {"N": n, "P2O5": p2o5, "K2O": k2o},
        "dose_for_area_kg": {"N": _round(n * area_ha), "P2O5": _round(p2o5 * area_ha), "K2O": _round(k2o * area_ha)},
        "nitrogen_from_phosphorus_source_kg_per_hectare": _round(n_from_p_ha),
        "products": totals,
        "applications": applications,
        "soil_ratings": soil_ratings,
        "warnings": warnings,
        "assumptions": [
            DATA["products_note"],
            DATA["split_note"],
            "Quantities are for the nutrient dose you supplied. This tool does not decide whether that dose suits your crop, soil or season.",
        ],
        "disclaimer": "A calculation aid, not an agronomic recommendation. Confirm the dose and timing with your Soil Health Card, local Krishi Vigyan Kendra or agriculture officer.",
    }
