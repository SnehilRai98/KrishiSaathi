import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { ExternalLink } from "lucide-react";
import { API, errorMessage } from "../lib/api";
import { Badge, EmptyState, Field, Loading, Notice, PageHeader, buttonPrimary, inputClass } from "../components/ui";
import PlanView, { type Plan } from "../components/PlanView";
import { describedBy } from "../lib/a11y";
import { EMPTY_FORM, MAX_DOSE, toRequest, validatePlan, type FormErrors, type PlanForm } from "../lib/fertilizer";

type Reference = {
  id: string;
  crop: string;
  region: string;
  N: number;
  P2O5: number;
  K2O: number;
  suggested_n_splits?: number;
  notes: string;
  verification: string;
  source_title: string;
  source_url: string;
};
type Options = {
  references: Reference[];
  products: Record<string, { name: string; N: number; P2O5: number; K2O: number }>;
  rating_limits: { N: { low_below: number; high_above: number }; P: { low_below: number; high_above: number }; K: { low_below: number; high_above: number }; caveat: string; source_title: string; source_url: string };
};

const radio = "h-4 w-4 accent-green-700";

export default function FertilizerAdvisor() {
  const [form, setForm] = useState<PlanForm>(EMPTY_FORM);
  const [errors, setErrors] = useState<FormErrors>({});
  const [options, setOptions] = useState<Options | null>(null);
  const [optionsError, setOptionsError] = useState("");
  const [plan, setPlan] = useState<Plan | null>(null);
  const [history, setHistory] = useState<Plan[]>([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function loadHistory() {
    setHistoryLoading(true);
    try {
      const response = await fetch(`${API}/api/fertilizer/history`);
      const data = await response.json();
      if (!response.ok) throw new Error(errorMessage(data, "Could not load saved plans."));
      setHistory(data);
      setHistoryError("");
    } catch (cause) {
      setHistoryError(cause instanceof Error ? cause.message : "Could not reach the API.");
    } finally {
      setHistoryLoading(false);
    }
  }

  useEffect(() => {
    let active = true;
    fetch(`${API}/api/fertilizer/options`)
      .then(async (response) => {
        const data = await response.json();
        if (!response.ok) throw new Error(errorMessage(data, "Could not load reference doses."));
        if (!Array.isArray(data?.references)) throw new Error("The reference doses could not be read.");
        if (active) setOptions(data);
      })
      .catch((cause) => active && setOptionsError(cause instanceof Error ? cause.message : "Could not reach the API."));
    void loadHistory();
    return () => {
      active = false;
    };
  }, []);

  function set<K extends keyof PlanForm>(key: K, value: PlanForm[K]) {
    setForm((current) => ({ ...current, [key]: value }));
    setErrors((current) => {
      const next = { ...current };
      delete next[key as string];
      return next;
    });
  }
  function setSoil(key: "n" | "p" | "k", part: "value" | "rating", value: string) {
    setForm((current) => ({ ...current, soil: { ...current.soil, [key]: { ...current.soil[key], [part]: value } } }));
  }

  const reference = options?.references.find((item) => item.id === form.referenceId);

  function chooseReference(id: string) {
    const picked = options?.references.find((item) => item.id === id);
    setForm((current) => ({ ...current, referenceId: id, nSplits: picked?.suggested_n_splits ? String(picked.suggested_n_splits) : current.nSplits }));
    setErrors((current) => ({ ...current, referenceId: "" }));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    const found = validatePlan(form);
    setErrors(found);
    const first = Object.keys(found)[0];
    if (first) {
      document.getElementById(`plan-${first}`)?.focus();
      return;
    }
    setBusy(true);
    try {
      const response = await fetch(`${API}/api/fertilizer/plan`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(toRequest(form)) });
      const data = await response.json();
      if (!response.ok) throw new Error(errorMessage(data, "Could not create the plan."));
      setPlan(data);
      await loadHistory();
      window.setTimeout(() => document.getElementById("plan-result")?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not reach the API. Check that the backend is running.");
    } finally {
      setBusy(false);
    }
  }

  const doseField = (key: "n" | "p2o5" | "k2o", label: string, hint: string) => (
    <Field id={`plan-${key}`} label={label} hint={hint} error={errors[key]} required>
      <input
        id={`plan-${key}`}
        type="number"
        inputMode="decimal"
        min={0}
        max={MAX_DOSE}
        step="any"
        value={form[key]}
        aria-invalid={Boolean(errors[key])}
        aria-describedby={describedBy(`plan-${key}`, hint, errors[key])}
        onChange={(event) => set(key, event.target.value)}
        className={inputClass}
      />
    </Field>
  );

  const limits = options?.rating_limits;
  const limitText = (key: "N" | "P" | "K") => (limits ? `Low below ${limits[key].low_below}, high above ${limits[key].high_above} kg/ha` : "");

  const soilRow = (key: "n" | "p" | "k", name: string) => (
    <div className="grid gap-2 sm:grid-cols-2">
      <Field id={`plan-soil_${key}`} label={`${name}: value (kg/ha)`} hint={limitText(key.toUpperCase() as "N" | "P" | "K")} error={errors[`soil_${key}`]}>
        <input
          id={`plan-soil_${key}`}
          type="number"
          inputMode="decimal"
          min={0}
          step="any"
          value={form.soil[key].value}
          aria-invalid={Boolean(errors[`soil_${key}`])}
          aria-describedby={describedBy(`plan-soil_${key}`, limitText(key.toUpperCase() as "N" | "P" | "K"), errors[`soil_${key}`])}
          onChange={(event) => setSoil(key, "value", event.target.value)}
          className={inputClass}
        />
      </Field>
      <Field id={`plan-soil_${key}_rating`} label={`${name}: rating printed on your report`} hint="Optional. If given, it is used instead of the number.">
        <select id={`plan-soil_${key}_rating`} value={form.soil[key].rating} onChange={(event) => setSoil(key, "rating", event.target.value)} aria-describedby={`plan-soil_${key}_rating-hint`} className={inputClass}>
          <option value="">Not given</option>
          <option value="low">Low</option>
          <option value="medium">Medium</option>
          <option value="high">High</option>
        </select>
      </Field>
    </div>
  );

  return (
    <section className="mx-auto max-w-4xl">
      <PageHeader title="Fertilizer planner">
        Turn a nutrient dose into a shopping and application plan: which fertilisers, how many kilograms for your area, and how to split them. The planner does the arithmetic; the dose itself comes from your Soil Health Card or lab report, or from a cited reference.
      </PageHeader>

      <Notice tone="info" className="mt-4" title="Where does the dose come from?">
        Your Soil Health Card or soil-testing lab report lists a recommended dose in kg per hectare for your crop. That is the best input. If you do not have one, a few state reference doses are offered below, each with its source. KrishiSaathi never decides a dose on its own.
      </Notice>

      <form onSubmit={submit} noValidate className="mt-6 space-y-6 rounded-2xl border bg-white p-6 shadow-sm">
        <fieldset>
          <legend className="text-base font-semibold text-slate-900">1. Nutrient dose</legend>
          <div className="mt-2 space-y-2">
            <label className="flex items-start gap-2 text-sm">
              <input type="radio" name="dose-source" className={`${radio} mt-1`} checked={form.doseSource === "own"} onChange={() => set("doseSource", "own")} />
              <span>
                <strong>Use the dose from my Soil Health Card or lab report</strong> (recommended)
              </span>
            </label>
            <label className="flex items-start gap-2 text-sm">
              <input type="radio" name="dose-source" className={`${radio} mt-1`} checked={form.doseSource === "reference"} onChange={() => set("doseSource", "reference")} />
              <span>Use a Maharashtra reference dose (a general starting point)</span>
            </label>
          </div>

          {form.doseSource === "own" ? (
            <div className="mt-4 grid gap-4 sm:grid-cols-3">
              {doseField("n", "Nitrogen, N (kg/ha)", "Use 0 if the report recommends none.")}
              {doseField("p2o5", "Phosphorus, P₂O₅ (kg/ha)", "Phosphate as P₂O₅.")}
              {doseField("k2o", "Potassium, K₂O (kg/ha)", "Potash as K₂O.")}
            </div>
          ) : (
            <div className="mt-4">
              {optionsError ? (
                <Notice tone="error">{optionsError}</Notice>
              ) : !options ? (
                <Loading>Loading reference doses…</Loading>
              ) : (
                <>
                  <Field id="plan-referenceId" label="Reference dose" error={errors.referenceId} required>
                    <select id="plan-referenceId" value={form.referenceId} onChange={(event) => chooseReference(event.target.value)} aria-invalid={Boolean(errors.referenceId)} aria-describedby={describedBy("plan-referenceId", undefined, errors.referenceId)} className={inputClass}>
                      <option value="">Choose…</option>
                      {options.references.map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.crop} · {item.region} · {item.N}:{item.P2O5}:{item.K2O}
                        </option>
                      ))}
                    </select>
                  </Field>
                  {reference && (
                    <div className="mt-3 rounded-xl border bg-slate-50 p-3 text-sm leading-6">
                      <p>
                        <strong>
                          {reference.N} N : {reference.P2O5} P₂O₅ : {reference.K2O} K₂O kg/ha
                        </strong>{" "}
                        {reference.verification === "verified" ? <Badge tone="green">Verified source</Badge> : <Badge tone="amber">Partly verified</Badge>}
                      </p>
                      <p className="mt-1 text-slate-700">{reference.notes}</p>
                      <a className="mt-1 inline-flex items-center gap-1 font-semibold text-green-800 underline" href={reference.source_url} target="_blank" rel="noreferrer noopener">
                        {reference.source_title} <ExternalLink size={13} aria-hidden="true" />
                        <span className="sr-only"> (opens in a new tab)</span>
                      </a>
                    </div>
                  )}
                  <p className="mt-2 text-xs text-slate-600">Only crops with a source I could verify are listed. More can be added in backend/fertilizer_data.json.</p>
                </>
              )}
            </div>
          )}
        </fieldset>

        <fieldset>
          <legend className="text-base font-semibold text-slate-900">2. Your farm</legend>
          <div className="mt-3 grid gap-4 sm:grid-cols-3">
            <Field id="plan-areaValue" label="Area" error={errors.areaValue} required>
              <input id="plan-areaValue" type="number" inputMode="decimal" min={0} step="any" value={form.areaValue} aria-invalid={Boolean(errors.areaValue)} aria-describedby={describedBy("plan-areaValue", undefined, errors.areaValue)} onChange={(event) => set("areaValue", event.target.value)} className={inputClass} />
            </Field>
            <Field id="plan-areaUnit" label="Unit" hint="40 gunthas = 1 acre">
              <select id="plan-areaUnit" value={form.areaUnit} onChange={(event) => set("areaUnit", event.target.value as PlanForm["areaUnit"])} aria-describedby="plan-areaUnit-hint" className={inputClass}>
                <option value="acre">Acres</option>
                <option value="guntha">Gunthas</option>
                <option value="hectare">Hectares</option>
              </select>
            </Field>
            <Field id="plan-label" label="Plan name (optional)" hint="For example: North plot, cotton">
              <input id="plan-label" maxLength={120} value={form.label} onChange={(event) => set("label", event.target.value)} aria-describedby="plan-label-hint" className={inputClass} />
            </Field>
          </div>
        </fieldset>

        <fieldset>
          <legend className="text-base font-semibold text-slate-900">3. Products and splits</legend>
          <div className="mt-3 grid gap-4 sm:grid-cols-3">
            <Field id="plan-pSource" label="Phosphorus from" hint="DAP also supplies nitrogen, which is deducted from urea.">
              <select id="plan-pSource" value={form.pSource} onChange={(event) => set("pSource", event.target.value as PlanForm["pSource"])} aria-describedby="plan-pSource-hint" className={inputClass}>
                <option value="dap">DAP (18-46-0)</option>
                <option value="ssp">SSP (0-16-0)</option>
              </select>
            </Field>
            <Field id="plan-kSource" label="Potassium from">
              <select id="plan-kSource" value={form.kSource} onChange={(event) => set("kSource", event.target.value as PlanForm["kSource"])} className={inputClass}>
                <option value="mop">MOP, muriate of potash (0-0-60)</option>
                <option value="sop">SOP, sulphate of potash (0-0-50)</option>
              </select>
            </Field>
            <Field id="plan-nSplits" label="Nitrogen applied in" hint="Follow your crop's package of practice for timing.">
              <select id="plan-nSplits" value={form.nSplits} onChange={(event) => set("nSplits", event.target.value)} aria-describedby="plan-nSplits-hint" className={inputClass}>
                {[1, 2, 3, 4].map((count) => (
                  <option key={count} value={count}>
                    {count} {count === 1 ? "part (all at sowing)" : "equal parts"}
                  </option>
                ))}
              </select>
            </Field>
          </div>
        </fieldset>

        <details className="rounded-xl border p-4">
          <summary className="cursor-pointer text-base font-semibold text-slate-900">4. Soil test results (optional)</summary>
          <p className="mt-2 text-sm leading-6 text-slate-700">
            Add your soil-test values to see whether each nutrient rates low, medium or high. Enter the rating printed on your report when it has one, because limits differ between states and labs.
            {limits && (
              <>
                {" "}
                Default limits come from <a className="font-semibold text-green-800 underline" href={limits.source_url} target="_blank" rel="noreferrer noopener">{limits.source_title}</a>. {limits.caveat}
              </>
            )}
          </p>
          <div className="mt-3 space-y-3">
            {soilRow("n", "Nitrogen")}
            {soilRow("p", "Phosphorus")}
            {soilRow("k", "Potassium")}
          </div>
        </details>

        <button disabled={busy} className={buttonPrimary}>
          {busy ? "Calculating…" : "Create my plan"}
        </button>
      </form>

      {error && (
        <Notice tone="error" className="mt-4">
          {error}
        </Notice>
      )}
      {plan && (
        <div id="plan-result" className="mt-6 scroll-mt-4">
          <h2 className="mb-3 text-xl font-semibold text-slate-900">Your plan</h2>
          <PlanView plan={plan} heading="h3" showPrint />
        </div>
      )}

      <h2 className="mt-10 text-xl font-semibold text-slate-900">Saved plans</h2>
      {historyLoading ? (
        <Loading>Loading saved plans…</Loading>
      ) : historyError ? (
        <Notice tone="error" className="mt-3">
          {historyError}
        </Notice>
      ) : history.length ? (
        <ul className="mt-3 space-y-3">
          {history.map((item) => (
            <li key={item.id}>
              <details className="rounded-xl border bg-white p-4">
                <summary className="cursor-pointer font-medium text-slate-900">
                  {item.label || "Fertiliser plan"} · {item.area.value} {item.area.unit}
                  <span className="ml-2 text-sm font-normal text-slate-600">{item.products.map((product) => `${product.product.split(" ")[0]} ${product.kg_for_area} kg`).join(", ")}</span>
                </summary>
                <div className="mt-3">
                  <PlanView plan={item} heading="h3" />
                </div>
              </details>
            </li>
          ))}
        </ul>
      ) : (
        <div className="mt-3">
          <EmptyState title="No saved plans yet.">Create a plan above and it will be saved here.</EmptyState>
        </div>
      )}
    </section>
  );
}
