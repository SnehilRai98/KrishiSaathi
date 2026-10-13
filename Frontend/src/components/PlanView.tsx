import { ExternalLink, Printer } from "lucide-react";
import { Badge, Notice, buttonSecondary } from "./ui";
import { formatDateTime } from "../lib/api";
import { AREA_LABELS } from "../lib/fertilizer";

export type PlanItem = { product: string; key: string; kg: number };
export type Plan = {
  id?: number;
  label: string;
  reference_id: string | null;
  dose_source?: string;
  area: { value: number; unit: keyof typeof AREA_LABELS; hectares: number; acres: number };
  dose_kg_per_hectare: { N: number; P2O5: number; K2O: number };
  dose_for_area_kg: { N: number; P2O5: number; K2O: number };
  nitrogen_from_phosphorus_source_kg_per_hectare: number;
  products: { key: string; product: string; grade: { N: number; P2O5: number; K2O: number }; kg_per_hectare: number; kg_for_area: number }[];
  applications: { stage: string; items: PlanItem[] }[];
  soil_ratings: { nutrient: string; label: string; rating: string; value: number | null; basis: string }[];
  warnings: string[];
  assumptions: string[];
  sources?: { title: string; url: string; note?: string; used_for?: string; verification?: string }[];
  disclaimer: string;
  created_at?: string;
};

const ratingTone = { low: "amber", medium: "green", high: "blue" } as const;
const grade = (g: { N: number; P2O5: number; K2O: number }) => `${g.N}-${g.P2O5}-${g.K2O}`;
const kg = (value: number) => `${value.toLocaleString(undefined, { maximumFractionDigits: 1 })} kg`;

export default function PlanView({ plan, heading = "h3", showPrint = false }: { plan: Plan; heading?: "h2" | "h3"; showPrint?: boolean }) {
  const Heading = heading;
  const unit = AREA_LABELS[plan.area.unit] ?? plan.area.unit;
  return (
    <article className="plan-print rounded-2xl border bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Heading className="text-lg font-semibold text-slate-900">{plan.label || "Fertiliser plan"}</Heading>
          <p className="text-sm text-slate-700">
            {plan.area.value} {unit} ({plan.area.hectares} ha) · dose per hectare: N {plan.dose_kg_per_hectare.N} · P₂O₅ {plan.dose_kg_per_hectare.P2O5} · K₂O {plan.dose_kg_per_hectare.K2O} kg
          </p>
          {plan.created_at && <p className="text-xs text-slate-600">{formatDateTime(plan.created_at)}</p>}
        </div>
        {showPrint && (
          <button type="button" className={`${buttonSecondary} print:hidden`} onClick={() => window.print()}>
            <Printer size={14} aria-hidden="true" /> Print or save as PDF
          </button>
        )}
      </div>

      {plan.soil_ratings.length > 0 && (
        <div className="mt-4">
          <p className="text-sm font-semibold text-slate-900">Your soil test</p>
          <ul className="mt-1 flex flex-wrap gap-2">
            {plan.soil_ratings.map((rating) => (
              <li key={rating.nutrient}>
                <Badge tone={ratingTone[rating.rating as keyof typeof ratingTone] ?? "slate"}>
                  {rating.label}: {rating.rating}
                  {rating.value !== null ? ` (${rating.value} kg/ha)` : ""} · {rating.basis}
                </Badge>
              </li>
            ))}
          </ul>
        </div>
      )}

      {plan.warnings.map((warning) => (
        <Notice key={warning} tone="warning" className="mt-4">
          {warning}
        </Notice>
      ))}

      <h4 className="mt-5 text-sm font-semibold text-slate-900">Fertiliser to buy for {plan.area.value} {unit}</h4>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full min-w-[28rem] text-left text-sm">
          <caption className="sr-only">Fertiliser products and quantities</caption>
          <thead>
            <tr className="border-b text-xs uppercase tracking-wide text-slate-600">
              <th scope="col" className="py-2 pr-3">Product</th>
              <th scope="col" className="py-2 pr-3">Grade (N-P-K)</th>
              <th scope="col" className="py-2 pr-3 text-right">For your area</th>
              <th scope="col" className="py-2 text-right">Per hectare</th>
            </tr>
          </thead>
          <tbody>
            {plan.products.map((item) => (
              <tr key={item.key} className="border-b last:border-0">
                <th scope="row" className="py-2 pr-3 font-medium text-slate-900">{item.product}</th>
                <td className="py-2 pr-3 tabular-nums text-slate-700">{grade(item.grade)}</td>
                <td className="py-2 pr-3 text-right text-base font-semibold tabular-nums text-green-900">{kg(item.kg_for_area)}</td>
                <td className="py-2 text-right tabular-nums text-slate-700">{kg(item.kg_per_hectare)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h4 className="mt-5 text-sm font-semibold text-slate-900">When to apply</h4>
      <ol className="mt-2 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {plan.applications.map((step) => (
          <li key={step.stage} className="rounded-xl border bg-slate-50 p-3 text-sm">
            <p className="font-semibold text-slate-900">{step.stage}</p>
            <ul className="mt-1 space-y-0.5">
              {step.items.map((item) => (
                <li key={item.key} className="flex justify-between gap-3">
                  <span>{item.product}</span>
                  <span className="tabular-nums font-medium">{kg(item.kg)}</span>
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ol>

      <details className="mt-5 text-sm">
        <summary className="cursor-pointer font-semibold text-green-800 print:hidden">Assumptions and sources</summary>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-slate-700">
          {plan.assumptions.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
        {plan.sources && plan.sources.length > 0 && (
          <ul className="mt-3 space-y-2">
            {plan.sources.map((source) => (
              <li key={source.url}>
                <a className="inline-flex items-center gap-1 font-semibold text-green-800 underline" href={source.url} target="_blank" rel="noreferrer noopener">
                  {source.title} <ExternalLink size={13} aria-hidden="true" />
                  <span className="sr-only"> (opens in a new tab)</span>
                </a>
                {source.verification === "partly_verified" && <span className="ml-2"><Badge tone="amber">Partly verified</Badge></span>}
                {(source.note || source.used_for) && <p className="text-slate-700">{source.note || source.used_for}</p>}
              </li>
            ))}
          </ul>
        )}
      </details>
      <p className="mt-4 rounded-lg bg-amber-50 p-3 text-xs leading-5 text-amber-950">{plan.disclaimer}</p>
    </article>
  );
}
