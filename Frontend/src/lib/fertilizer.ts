/** Form helpers for the fertiliser planner. The server repeats every check. */

export const MAX_DOSE = 600;
export const MAX_SOIL_VALUE = 10000;

export type PlanForm = {
  doseSource: "own" | "reference";
  referenceId: string;
  n: string;
  p2o5: string;
  k2o: string;
  areaValue: string;
  areaUnit: "acre" | "hectare" | "guntha";
  label: string;
  pSource: "dap" | "ssp";
  kSource: "mop" | "sop";
  nSplits: string;
  soil: Record<"n" | "p" | "k", { value: string; rating: "" | "low" | "medium" | "high" }>;
};

export const EMPTY_FORM: PlanForm = {
  doseSource: "own",
  referenceId: "",
  n: "",
  p2o5: "",
  k2o: "",
  areaValue: "",
  areaUnit: "acre",
  label: "",
  pSource: "dap",
  kSource: "mop",
  nSplits: "2",
  soil: { n: { value: "", rating: "" }, p: { value: "", rating: "" }, k: { value: "", rating: "" } },
};

export type FormErrors = Record<string, string>;

const parse = (raw: string) => (raw.trim() === "" ? NaN : Number(raw));

export function validatePlan(form: PlanForm): FormErrors {
  const errors: FormErrors = {};
  if (form.doseSource === "reference") {
    if (!form.referenceId) errors.referenceId = "Choose a reference dose.";
  } else {
    const doses = (["n", "p2o5", "k2o"] as const).map((key) => {
      const value = parse(form[key]);
      if (Number.isNaN(value)) errors[key] = "Enter a number (use 0 if this nutrient is not recommended).";
      else if (!Number.isFinite(value) || value < 0) errors[key] = "Dose cannot be negative.";
      else if (value > MAX_DOSE) errors[key] = `Dose must be ${MAX_DOSE} kg/ha or less. Check the number and its unit.`;
      return value;
    });
    if (doses.every((value) => value === 0)) errors.n = errors.n ?? "Enter a dose for at least one nutrient.";
  }
  const area = parse(form.areaValue);
  if (Number.isNaN(area)) errors.areaValue = "Enter your farm area.";
  else if (!(area > 0)) errors.areaValue = "Area must be more than zero.";
  else if (area > 100000) errors.areaValue = "Area is too large. Check the number and unit.";
  (["n", "p", "k"] as const).forEach((key) => {
    const raw = form.soil[key].value;
    if (raw.trim() !== "") {
      const value = Number(raw);
      if (!Number.isFinite(value) || value < 0) errors[`soil_${key}`] = "Soil value cannot be negative.";
      else if (value > MAX_SOIL_VALUE) errors[`soil_${key}`] = `Soil value must be ${MAX_SOIL_VALUE} or less.`;
    }
  });
  return errors;
}

export function toRequest(form: PlanForm) {
  const soil = (key: "n" | "p" | "k") => {
    const { value, rating } = form.soil[key];
    if (value.trim() === "" && !rating) return undefined;
    return { value: value.trim() === "" ? null : Number(value), rating: rating || null };
  };
  return {
    label: form.label.trim(),
    dose_source: form.doseSource,
    reference_id: form.doseSource === "reference" ? form.referenceId : null,
    n: form.doseSource === "own" ? Number(form.n) : null,
    p2o5: form.doseSource === "own" ? Number(form.p2o5) : null,
    k2o: form.doseSource === "own" ? Number(form.k2o) : null,
    area_value: Number(form.areaValue),
    area_unit: form.areaUnit,
    p_source: form.pSource,
    k_source: form.kSource,
    n_splits: Number(form.nSplits),
    soil_n: soil("n"),
    soil_p: soil("p"),
    soil_k: soil("k"),
  };
}

export const AREA_LABELS = { acre: "acres", hectare: "hectares", guntha: "gunthas" } as const;
