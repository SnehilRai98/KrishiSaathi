import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import FertilizerAdvisor from "./FertilizerAdvisor";
import { EMPTY_FORM, toRequest, validatePlan } from "../lib/fertilizer";
import { mockFetch } from "../test/helpers";

beforeEach(() => {
  window.HTMLElement.prototype.scrollIntoView = vi.fn();
});
afterEach(() => vi.unstubAllGlobals());

const options = {
  references: [
    { id: "cotton-irrigated-mh", crop: "Cotton, irrigated", region: "Maharashtra", N: 100, P2O5: 50, K2O: 50, suggested_n_splits: 3, notes: "State package note.", verification: "verified", source_title: "Package of Practices for Cotton", source_url: "https://example.org/cotton.pdf" },
    { id: "wheat-irrigated-mpkv", crop: "Wheat, irrigated", region: "Maharashtra", N: 120, P2O5: 60, K2O: 40, notes: "Check variety.", verification: "partly_verified", source_title: "MPKV wheat", source_url: "https://example.org/wheat.pdf" },
  ],
  products: {},
  rating_limits: { N: { low_below: 280, high_above: 560 }, P: { low_below: 10, high_above: 25 }, K: { low_below: 120, high_above: 280 }, caveat: "Limits differ between labs.", source_title: "SHC definitions", source_url: "https://example.org/shc" },
};

const plan = {
  id: 7,
  label: "My dose",
  reference_id: null,
  area: { value: 2, unit: "acre", hectares: 0.8094, acres: 2 },
  dose_kg_per_hectare: { N: 100, P2O5: 50, K2O: 50 },
  dose_for_area_kg: { N: 80.9, P2O5: 40.5, K2O: 40.5 },
  nitrogen_from_phosphorus_source_kg_per_hectare: 19.6,
  products: [
    { key: "urea", product: "Urea", grade: { N: 46, P2O5: 0, K2O: 0 }, kg_per_hectare: 174.9, kg_for_area: 141.6 },
    { key: "dap", product: "DAP (di-ammonium phosphate)", grade: { N: 18, P2O5: 46, K2O: 0 }, kg_per_hectare: 108.7, kg_for_area: 88 },
  ],
  applications: [
    { stage: "Basal (at sowing or planting)", items: [{ product: "DAP (di-ammonium phosphate)", key: "dap", kg: 88 }, { product: "Urea", key: "urea", kg: 24.2 }] },
    { stage: "Top-dress 1 of 1", items: [{ product: "Urea", key: "urea", kg: 117.4 }] },
  ],
  soil_ratings: [{ nutrient: "P", label: "Phosphorus", rating: "low", value: 6, basis: "computed with default limits" }],
  warnings: ["A reference dose is a general starting point."],
  assumptions: ["Use the grade printed on your bag."],
  sources: [{ title: "FAO guidelines", url: "https://example.org/fao", used_for: "General practice." }],
  disclaimer: "A calculation aid, not an agronomic recommendation.",
  created_at: "2026-10-10T08:30:00Z",
};

function routes(extra: [string, (url: string, init?: RequestInit) => unknown][] = []) {
  return mockFetch([...extra, ["/api/fertilizer/options", () => options], ["/api/fertilizer/history", () => []]]);
}
const fillOwn = async (n = "100", p = "50", k = "50", area = "2") => {
  await userEvent.type(screen.getByLabelText(/^Nitrogen, N/), n);
  await userEvent.type(screen.getByLabelText(/^Phosphorus, P/), p);
  await userEvent.type(screen.getByLabelText(/^Potassium, K/), k);
  await userEvent.type(screen.getByLabelText(/^Area/), area);
};

describe("FertilizerAdvisor planner", () => {
  it("sends the dose, area and product choices and shows the products to buy and the schedule", async () => {
    const fetchMock = routes([["/api/fertilizer/plan", () => plan]]);
    render(<FertilizerAdvisor />);
    await fillOwn();
    await userEvent.selectOptions(screen.getByLabelText("Unit"), "acre");
    await userEvent.selectOptions(screen.getByLabelText("Phosphorus from"), "ssp");
    await userEvent.click(screen.getByRole("button", { name: /create my plan/i }));

    const result = (await screen.findByRole("heading", { name: "Your plan" })).parentElement as HTMLElement;
    expect(within(result).getByText("141.6 kg")).toBeInTheDocument();
    expect(within(result).getByRole("table")).toBeInTheDocument();
    expect(within(result).getByText("Basal (at sowing or planting)")).toBeInTheDocument();
    expect(within(result).getByText(/Phosphorus: low/)).toBeInTheDocument();
    expect(within(result).getByText(/general starting point/)).toBeInTheDocument();
    expect(within(result).getByText(/not an agronomic recommendation/)).toBeInTheDocument();
    expect(within(result).getByRole("button", { name: /print or save as pdf/i })).toBeInTheDocument();

    const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
    expect(JSON.parse(String(post?.[1]?.body))).toMatchObject({ dose_source: "own", n: 100, p2o5: 50, k2o: 50, area_value: 2, area_unit: "acre", p_source: "ssp", k_source: "mop", n_splits: 2 });
  });

  it("blocks invalid input with visible messages and never calls the API", async () => {
    const fetchMock = routes();
    render(<FertilizerAdvisor />);
    await userEvent.type(screen.getByLabelText(/^Nitrogen, N/), "-5");
    await userEvent.type(screen.getByLabelText(/^Potassium, K/), "9999");
    await userEvent.click(screen.getByRole("button", { name: /create my plan/i }));
    expect(screen.getByText(/cannot be negative/i)).toBeInTheDocument();
    expect(screen.getByText(/600 kg\/ha or less/i)).toBeInTheDocument();
    expect(screen.getByText(/enter a number \(use 0/i)).toBeInTheDocument();
    expect(screen.getByText(/enter your farm area/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^Nitrogen, N/)).toHaveAttribute("aria-invalid", "true");
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
  });

  it("offers cited reference doses with their verification level and sets the suggested splits", async () => {
    const fetchMock = routes([["/api/fertilizer/plan", () => ({ ...plan, reference_id: "cotton-irrigated-mh" })]]);
    render(<FertilizerAdvisor />);
    await userEvent.click(screen.getByLabelText(/Maharashtra reference dose/));
    await userEvent.selectOptions(await screen.findByLabelText(/^Reference dose/), "cotton-irrigated-mh");
    expect(screen.getByText("Verified source")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Package of Practices for Cotton/ })).toHaveAttribute("href", "https://example.org/cotton.pdf");
    expect(screen.getByLabelText("Nitrogen applied in")).toHaveValue("3");
    await userEvent.selectOptions(screen.getByLabelText(/^Reference dose/), "wheat-irrigated-mpkv");
    expect(screen.getByText("Partly verified")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(/^Area/), "1");
    await userEvent.click(screen.getByRole("button", { name: /create my plan/i }));
    await screen.findByRole("heading", { name: "Your plan" });
    const body = JSON.parse(String(fetchMock.mock.calls.find(([, init]) => init?.method === "POST")?.[1]?.body));
    expect(body).toMatchObject({ dose_source: "reference", reference_id: "wheat-irrigated-mpkv", n: null });
  });

  it("requires a reference dose to be chosen", async () => {
    routes();
    render(<FertilizerAdvisor />);
    await userEvent.click(screen.getByLabelText(/Maharashtra reference dose/));
    await userEvent.type(screen.getByLabelText(/^Area/), "1");
    await userEvent.click(screen.getByRole("button", { name: /create my plan/i }));
    expect(screen.getByText("Choose a reference dose.")).toBeInTheDocument();
  });

  it("explains the dose source and its own limits up front", () => {
    routes();
    render(<FertilizerAdvisor />);
    expect(screen.getByText(/never decides a dose on its own/i)).toBeInTheDocument();
    expect(screen.getByText(/Soil Health Card or lab report/, { selector: "strong" })).toBeInTheDocument();
  });

  it("shows server validation errors", async () => {
    routes([["/api/fertilizer/plan", () => ({ __status: 422, body: { detail: [{ loc: ["body"], msg: "Area is outside the supported range." }] } })]]);
    render(<FertilizerAdvisor />);
    await fillOwn("10", "10", "10", "5");
    await userEvent.click(screen.getByRole("button", { name: /create my plan/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Area is outside the supported range/);
  });

  it("lists saved plans with their products and the full plan on expansion", async () => {
    mockFetch([["/api/fertilizer/options", () => options], ["/api/fertilizer/history", () => [plan]]]);
    render(<FertilizerAdvisor />);
    const summary = await screen.findByText(/My dose · 2 acre/);
    expect(summary.closest("summary")).toHaveTextContent(/Urea 141.6 kg/);
    await userEvent.click(summary);
    expect(screen.getAllByText("Top-dress 1 of 1").length).toBeGreaterThan(0);
  });

  it("shows empty and error states for saved plans", async () => {
    routes();
    const { unmount } = render(<FertilizerAdvisor />);
    expect(await screen.findByText("No saved plans yet.")).toBeInTheDocument();
    unmount();
    mockFetch([["/api/fertilizer/options", () => options], ["/api/fertilizer/history", () => ({ detail: "Database is unavailable." })]], 503);
    render(<FertilizerAdvisor />);
    expect(await screen.findByText("Database is unavailable.")).toBeInTheDocument();
  });

  it("uses a rating printed on the report in the request", async () => {
    const fetchMock = routes([["/api/fertilizer/plan", () => plan]]);
    render(<FertilizerAdvisor />);
    await fillOwn("10", "10", "10", "1");
    await userEvent.click(screen.getByText(/Soil test results/));
    await userEvent.selectOptions(screen.getByLabelText(/Phosphorus: rating printed/), "low");
    await userEvent.type(screen.getByLabelText(/Nitrogen: value/), "250");
    await userEvent.click(screen.getByRole("button", { name: /create my plan/i }));
    await screen.findByRole("heading", { name: "Your plan" });
    const body = JSON.parse(String(fetchMock.mock.calls.find(([, init]) => init?.method === "POST")?.[1]?.body));
    expect(body.soil_p).toEqual({ value: null, rating: "low" });
    expect(body.soil_n).toEqual({ value: 250, rating: null });
    expect(body.soil_k).toBeUndefined();
  });
});

describe("validatePlan", () => {
  const ok = { ...EMPTY_FORM, n: "0", p2o5: "12.5", k2o: "600", areaValue: "3" };
  it("accepts zero, decimals and the maximum", () => expect(validatePlan(ok)).toEqual({}));
  it("rejects blanks, negatives, too-large values and all-zero doses", () => {
    expect(Object.keys(validatePlan({ ...ok, n: "", p2o5: "-1", k2o: "601", areaValue: "0" })).sort()).toEqual(["areaValue", "k2o", "n", "p2o5"]);
    expect(validatePlan({ ...ok, n: "0", p2o5: "0", k2o: "0" }).n).toMatch(/at least one nutrient/);
  });
  it("validates soil values only when given", () => {
    expect(validatePlan({ ...ok, soil: { ...ok.soil, n: { value: "-3", rating: "" } } }).soil_n).toMatch(/negative/);
    expect(validatePlan({ ...ok, soil: { ...ok.soil, n: { value: "", rating: "low" } } })).toEqual({});
  });
  it("builds a request that matches the API", () => {
    expect(toRequest({ ...ok, label: " North ", nSplits: "3" })).toMatchObject({ label: "North", n: 0, p2o5: 12.5, k2o: 600, area_value: 3, n_splits: 3, soil_n: undefined });
  });
});
