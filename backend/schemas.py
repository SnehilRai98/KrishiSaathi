from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

import config
import fertilizer_engine as engine

Rating = Literal["low", "medium", "high"]


class SoilValue(BaseModel):
    """One soil-test result: a number in kg/ha, a Low/Medium/High rating printed on the report, or both."""

    model_config = ConfigDict(extra="forbid")

    value: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    rating: Rating | None = None

    @field_validator("value")
    @classmethod
    def within_limit(cls, value: float | None) -> float | None:
        if value is not None and value > config.NPK_MAX_VALUE:
            raise ValueError(f"Value must be {config.NPK_MAX_VALUE:g} or less. Check the number and its unit (kg/ha).")
        return value


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(default="", max_length=120)
    dose_source: Literal["own", "reference"] = "own"
    reference_id: str | None = Field(default=None, max_length=60)
    # Nutrient doses in kg per hectare, for dose_source="own".
    n: float | None = Field(default=None, ge=0, le=engine.MAX_DOSE_KG_PER_HA, allow_inf_nan=False)
    p2o5: float | None = Field(default=None, ge=0, le=engine.MAX_DOSE_KG_PER_HA, allow_inf_nan=False)
    k2o: float | None = Field(default=None, ge=0, le=engine.MAX_DOSE_KG_PER_HA, allow_inf_nan=False)
    area_value: float = Field(gt=0, le=100_000, allow_inf_nan=False)
    area_unit: Literal["acre", "hectare", "guntha"]
    p_source: Literal["dap", "ssp"] = "dap"
    k_source: Literal["mop", "sop"] = "mop"
    n_splits: int = Field(default=2, ge=1, le=4)
    soil_n: SoilValue | None = None
    soil_p: SoilValue | None = None
    soil_k: SoilValue | None = None

    @field_validator("label")
    @classmethod
    def tidy_label(cls, value: str) -> str:
        return " ".join(value.split())

    @model_validator(mode="after")
    def check_dose_source(self) -> "PlanRequest":
        if self.dose_source == "reference":
            if not self.reference_id or engine.reference_by_id(self.reference_id) is None:
                raise ValueError("Choose one of the listed reference doses.")
        else:
            missing = [name for name, value in (("n", self.n), ("p2o5", self.p2o5), ("k2o", self.k2o)) if value is None]
            if missing:
                raise ValueError("Enter the nutrient doses from your report (use 0 for a nutrient that is not recommended).")
            if (self.n or 0) + (self.p2o5 or 0) + (self.k2o or 0) <= 0:
                raise ValueError("Enter a dose for at least one nutrient.")
        return self
