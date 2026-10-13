import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import CropHealth from "./CropHealth";
import { mockFetch, mockUpload } from "../test/helpers";

beforeEach(() => {
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: () => "blob:preview", revokeObjectURL: () => {} }));
});
afterEach(() => vi.unstubAllGlobals());

const leaf = () => new File([new Uint8Array([1, 2, 3])], "leaf.png", { type: "image/png" });

describe("CropHealth", () => {
  it("shows an empty history state", async () => {
    mockFetch([["/api/crop-health/history", () => []]]);
    render(<CropHealth />);
    expect(await screen.findByText("No crop uploads yet.")).toBeInTheDocument();
  });

  it("states the screening-aid limits and tips up front", async () => {
    mockFetch([["/api/crop-health/history", () => []]]);
    render(<CropHealth />);
    expect(screen.getByText(/A screening aid, not a diagnosis/)).toBeInTheDocument();
    expect(screen.getByText(/does not recommend pesticides/i)).toBeInTheDocument();
    expect(screen.getByText(/Photos of other plants give unreliable results/)).toBeInTheDocument();
  });

  it("shows a preview with file details and lets the user remove it", async () => {
    mockFetch([["/api/crop-health/history", () => []]]);
    render(<CropHealth />);
    await userEvent.upload(screen.getByLabelText(/crop image/i), leaf());
    expect(await screen.findByAltText("Selected crop preview")).toBeInTheDocument();
    expect(screen.getByText("leaf.png")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /remove image/i }));
    expect(screen.queryByAltText("Selected crop preview")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /analyze image/i })).toBeDisabled();
  });

  it("rejects images over the size limit before uploading", async () => {
    mockFetch([["/api/crop-health/history", () => []]]);
    render(<CropHealth />);
    const big = new File([new Uint8Array(11 * 1024 * 1024)], "big.png", { type: "image/png" });
    await userEvent.upload(screen.getByLabelText(/crop image/i), big);
    expect(await screen.findByRole("alert")).toHaveTextContent(/10 MB or smaller/);
    expect(screen.queryByAltText("Selected crop preview")).not.toBeInTheDocument();
  });

  it("accepts WebP images", async () => {
    mockFetch([["/api/crop-health/history", () => []]]);
    render(<CropHealth />);
    await userEvent.upload(screen.getByLabelText(/crop image/i), new File([new Uint8Array([1])], "leaf.webp", { type: "image/webp" }));
    expect(await screen.findByAltText("Selected crop preview")).toBeInTheDocument();
  });

  it("warns that a 'healthy' result is not a clean bill of health", async () => {
    mockFetch([["/api/crop-health/history", () => []]]);
    mockUpload({ status: "diagnosed", disease: "Apple — healthy", healthy: true, confidence: 0.9, top_predictions: [], guidance: [], message: "Looks healthy: Apple." });
    render(<CropHealth />);
    await userEvent.upload(screen.getByLabelText(/crop image/i), leaf());
    await userEvent.click(screen.getByRole("button", { name: /analyze image/i }));
    expect(await screen.findByText(/only means the model did not match a disease it knows/i)).toBeInTheDocument();
    expect(screen.getByText(/High score, but a high score can still be wrong/)).toBeInTheDocument();
  });

  it("shows readable history with status, local time and closest matches", async () => {
    mockFetch([
      [
        "/api/crop-health/history",
        () => [
          { id: 1, image_filename: "a.png", disease: "Tomato — Late blight", confidence: 0.91, status: "diagnosed", quality_feedback: "x", created_at: "2026-10-10T08:30:00Z", top_predictions: [{ label: "Tomato — Late blight", confidence: 0.91 }, { label: "Tomato — Early blight", confidence: 0.05 }] },
          { id: 2, image_filename: "b.png", disease: null, confidence: 0.3, status: "low_confidence", quality_feedback: "Not confident.", created_at: "2026-10-09T08:30:00Z", top_predictions: [] },
        ],
      ],
    ]);
    render(<CropHealth />);
    expect(await screen.findByText("Result given")).toBeInTheDocument();
    expect(screen.getByText("Low confidence")).toBeInTheDocument();
    expect(screen.getByText(/score 91.0%/)).toBeInTheDocument();
    await userEvent.click(screen.getByText("Closest matches", { selector: "summary" }));
    expect(screen.getByText(/Tomato — Early blight · 5.0%/)).toBeInTheDocument();
  });

  it("uploads a leaf and shows the disease result with closest matches", async () => {
    mockFetch([["/api/crop-health/history", () => []]]);
    mockUpload({
      status: "diagnosed",
      disease: "Tomato — Late blight",
      healthy: false,
      confidence: 0.97,
      top_predictions: [
        { label: "Tomato — Late blight", confidence: 0.97 },
        { label: "Tomato — Leaf Mold", confidence: 0.02 },
      ],
      guidance: ["This is a screening aid, not a diagnosis."],
      message: "Possible late blight on tomato.",
    });
    render(<CropHealth />);
    await userEvent.upload(screen.getByLabelText(/crop image/i), leaf());
    await userEvent.click(screen.getByRole("button", { name: /analyze image/i }));
    expect(await screen.findByRole("heading", { name: "Tomato — Late blight" })).toBeInTheDocument();
    expect(screen.getByText("Possible late blight on tomato.")).toBeInTheDocument();
    expect(screen.getByText(/Model score: 97.0%/)).toBeInTheDocument();
    expect(screen.getByText("Closest matches")).toBeInTheDocument();
  });

  it("explains when the model cannot give a confident result", async () => {
    mockFetch([["/api/crop-health/history", () => []]]);
    mockUpload({ status: "low_confidence", disease: null, confidence: 0.4, top_predictions: [], guidance: [], message: "The model is not confident." });
    render(<CropHealth />);
    await userEvent.upload(screen.getByLabelText(/crop image/i), leaf());
    await userEvent.click(screen.getByRole("button", { name: /analyze image/i }));
    expect(await screen.findByRole("heading", { name: /not confident enough/i })).toBeInTheDocument();
  });

  it("shows the API error message when the upload is rejected", async () => {
    mockFetch([["/api/crop-health/history", () => []]]);
    mockUpload({ detail: "Image must be 10 MB or smaller." }, 413);
    render(<CropHealth />);
    await userEvent.upload(screen.getByLabelText(/crop image/i), leaf());
    await userEvent.click(screen.getByRole("button", { name: /analyze image/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Image must be 10 MB or smaller.");
  });

  it("rejects unsupported file types before uploading", async () => {
    mockFetch([["/api/crop-health/history", () => []]]);
    render(<CropHealth />);
    const input = screen.getByLabelText(/crop image/i);
    // `applyAccept: false` lets the test bypass the input's accept filter, like a drag-and-drop would.
    await userEvent.setup({ applyAccept: false }).upload(input, new File(["x"], "leaf.gif", { type: "image/gif" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Choose a JPG, PNG or WebP image.");
  });
});


describe("CropHealth: explanations and evidence", () => {
  const diagnosed = { status: "diagnosed", disease: "Tomato — Late blight", healthy: false, confidence: 0.82, top_predictions: [], guidance: [], message: "Possible late blight on tomato.", low_confidence_threshold: 0.6 };

  it("requests a heat-map by default and shows it with an honest caption", async () => {
    mockFetch([["/api/crop-health/model", () => ({ status: {}, card: null })], ["/api/crop-health/history", () => []]]);
    const urls = mockUpload({ ...diagnosed, heatmap: "data:image/png;base64,AAAA", evidence: "field" });
    render(<CropHealth />);
    await userEvent.upload(screen.getByLabelText(/crop image/i), leaf());
    await userEvent.click(screen.getByRole("button", { name: /analyze image/i }));
    const image = await screen.findByAltText(/Heat-map overlay/);
    expect(image).toHaveAttribute("src", "data:image/png;base64,AAAA");
    expect(screen.getByText(/not whether it is right/i)).toBeInTheDocument();
    expect(urls[0]).toContain("explain=true");
  });

  it("tells the farmer what the field test measured for a score like theirs", async () => {
    mockFetch([["/api/crop-health/model", () => ({ status: {}, card: null })], ["/api/crop-health/history", () => []]]);
    mockUpload({ ...diagnosed, heatmap: null, evidence: "field", reliability: { score_at_least: 0.8, accuracy_when_answered: 0.857, share_of_photos_answered: 0.27, photos_tested: 236, dataset: "PlantDoc test split" } });
    render(<CropHealth />);
    await userEvent.upload(screen.getByLabelText(/crop image/i), leaf());
    await userEvent.click(screen.getByRole("button", { name: /analyze image/i }));
    expect(await screen.findByText(/it was right 85.7% of the time/)).toBeInTheDocument();
    expect(screen.getByText(/236 real photos/)).toBeInTheDocument();
    expect(screen.getByText(/not a guarantee for your leaf/)).toBeInTheDocument();
  });

  it("does not request a heat-map when the box is unticked", async () => {
    mockFetch([["/api/crop-health/model", () => ({ status: {}, card: null })], ["/api/crop-health/history", () => []]]);
    const urls = mockUpload({ ...diagnosed, heatmap: null, evidence: "field" });
    render(<CropHealth />);
    await userEvent.click(screen.getByLabelText(/Show a heat-map/));
    await userEvent.upload(screen.getByLabelText(/crop image/i), leaf());
    await userEvent.click(screen.getByRole("button", { name: /analyze image/i }));
    await screen.findByText("Possible late blight on tomato.");
    expect(urls[0]).not.toContain("explain");
    expect(screen.queryByAltText(/Heat-map overlay/)).not.toBeInTheDocument();
  });

  it("warns when a class has only lab-photo evidence", async () => {
    mockFetch([["/api/crop-health/model", () => ({ status: {}, card: null })], ["/api/crop-health/history", () => []]]);
    mockUpload({ ...diagnosed, heatmap: null, evidence: "lab_only" });
    render(<CropHealth />);
    await userEvent.upload(screen.getByLabelText(/crop image/i), leaf());
    await userEvent.click(screen.getByRole("button", { name: /analyze image/i }));
    expect(await screen.findByText(/learned from lab photos only/i)).toBeInTheDocument();
  });

  it("shows measured field results, with the baseline for comparison, in the reliability panel", async () => {
    mockFetch([
      ["/api/crop-health/model", () => ({ status: { field_tuned: true }, card: { metrics: { field_test: { n: 236, top1: 0.5, crop_top1: 0.7, baseline_top1: 0.13, baseline_crop_top1: 0.3, dataset: "PlantDoc test split" }, lab_test: { n: 380, top1: 0.9, baseline_top1: 0.93 }, non_leaf: { n: 19, shown_as_result: 0.1, baseline_shown_as_result: 0.2 } }, limitations: ["Only 14 crops."] } })],
      ["/api/crop-health/history", () => []],
    ]);
    render(<CropHealth />);
    await userEvent.click(screen.getByText("How reliable is this model?"));
    expect(await screen.findByText(/PlantDoc test split/)).toBeInTheDocument();
    expect(screen.getByText(/The earlier lab-only model scored 13.0% and 30.0%/)).toBeInTheDocument();
    expect(screen.getByText(/Lab photos are far easier/)).toBeInTheDocument();
    expect(screen.getByText("Only 14 crops.")).toBeInTheDocument();
  });

  it("says plainly when no evaluation exists", async () => {
    mockFetch([["/api/crop-health/model", () => ({ status: {}, card: null })], ["/api/crop-health/history", () => []]]);
    render(<CropHealth />);
    await userEvent.click(screen.getByText("How reliable is this model?"));
    expect(screen.getByText(/No evaluation report is available/)).toBeInTheDocument();
  });
});
