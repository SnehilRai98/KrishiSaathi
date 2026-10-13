import { useCallback, useEffect, useRef, useState } from "react";
import { ImagePlus, Trash2, UploadCloud } from "lucide-react";
import { API, errorMessage, formatDateTime } from "../lib/api";
import { scoreNote } from "../lib/crop";
import { Badge, EmptyState, Loading, Notice, PageHeader, buttonPrimary, buttonSecondary } from "../components/ui";

const MAX_MB = 10;
const MAX_BYTES = MAX_MB * 1024 * 1024;
const ALLOWED_TYPES = ["image/jpeg", "image/png", "image/webp"];
const SUPPORTED_CROPS =
  "apple, blueberry, cherry, corn (maize), grape, orange, peach, bell pepper, potato, raspberry, soybean, squash, strawberry and tomato";

type TopPrediction = { label: string; confidence: number };
type CropPrediction = {
  status: string;
  disease: string | null;
  healthy: boolean | null;
  confidence: number | null;
  top_predictions: TopPrediction[];
  guidance: string[];
  message: string;
  threshold: number;
  heatmap: string | null;
  evidence: string | null;
  reliability: { score_at_least: number; accuracy_when_answered: number; share_of_photos_answered: number; photos_tested: number; dataset: string } | null;
};
type ModelCard = {
  status?: { field_tuned?: boolean };
  card?: {
    model_version?: string;
    metrics?: {
      field_test?: { n: number; top1: number; crop_top1: number; baseline_top1: number; baseline_crop_top1: number; dataset: string };
      lab_test?: { n: number; top1: number; baseline_top1: number };
      non_leaf?: { n: number; shown_as_result: number; baseline_shown_as_result: number };
    };
    limitations?: string[];
  } | null;
};
type CropHistory = {
  id: number;
  image_filename: string;
  disease: string | null;
  confidence: number | null;
  status: string;
  quality_feedback: string | null;
  top_predictions?: TopPrediction[];
  created_at: string;
};

const percent = (value: number) => `${(value * 100).toFixed(1)}%`;
const formatSize = (bytes: number) => (bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`);

function resultStyle(result: CropPrediction) {
  if (result.status === "diagnosed") return result.healthy ? "border-green-200 bg-green-50" : "border-amber-300 bg-amber-50";
  return "border-slate-300 bg-slate-50";
}

function resultTitle(result: CropPrediction) {
  switch (result.status) {
    case "diagnosed":
      return result.disease ?? "Result";
    case "low_confidence":
      return "Not confident enough to give a result";
    case "no_leaf_detected":
      return "No leaf detected";
    default:
      return "Image quality feedback";
  }
}

const statusLabel: Record<string, { text: string; tone: "green" | "amber" | "slate" }> = {
  diagnosed: { text: "Result given", tone: "green" },
  low_confidence: { text: "Low confidence", tone: "amber" },
  no_leaf_detected: { text: "No leaf detected", tone: "amber" },
  image_quality_only: { text: "Image check only", tone: "slate" },
};

function historySummary(item: CropHistory) {
  if (item.status === "diagnosed" && item.disease) return item.disease;
  return item.quality_feedback || item.status.replace(/_/g, " ");
}

export default function CropHealth() {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState("");
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [error, setError] = useState("");
  const [prediction, setPrediction] = useState<CropPrediction | null>(null);
  const [history, setHistory] = useState<CropHistory[]>([]);
  const [historyError, setHistoryError] = useState("");
  const [historyLoading, setHistoryLoading] = useState(true);
  const [explain, setExplain] = useState(true);
  const [modelInfo, setModelInfo] = useState<ModelCard | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    try {
      const response = await fetch(`${API}/api/crop-health/history`);
      const data = await response.json();
      if (!response.ok) throw new Error(errorMessage(data, "Could not load crop history."));
      setHistory(data);
      setHistoryError("");
    } catch (cause) {
      setHistoryError(cause instanceof Error ? cause.message : "Could not reach the API.");
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadHistory();
    fetch(`${API}/api/crop-health/model`)
      .then((response) => (response.ok ? response.json() : null))
      .then((body) => body && setModelInfo(body))
      .catch(() => undefined); // the panel is optional
  }, [loadHistory]);

  useEffect(
    () => () => {
      if (preview) URL.revokeObjectURL(preview);
    },
    [preview],
  );

  function choose(next?: File) {
    setError("");
    setPrediction(null);
    setFile(null);
    setPreview("");
    if (!next) return;
    if (!ALLOWED_TYPES.includes(next.type)) {
      setError("Choose a JPG, PNG or WebP image.");
      return;
    }
    if (next.size === 0) {
      setError("That file is empty. Choose a different image.");
      return;
    }
    if (next.size > MAX_BYTES) {
      setError(`That image is ${formatSize(next.size)}. Choose one that is ${MAX_MB} MB or smaller.`);
      return;
    }
    setFile(next);
    setPreview(URL.createObjectURL(next));
  }

  function clearSelection() {
    choose(undefined);
    if (inputRef.current) inputRef.current.value = "";
  }

  async function submit() {
    if (!file) return;
    setBusy(true);
    setUploadProgress(0);
    setError("");
    setPrediction(null);
    const body = new FormData();
    body.append("image", file);
    try {
      const data = await new Promise<Record<string, unknown>>((resolve, reject) => {
        const request = new XMLHttpRequest();
        request.open("POST", `${API}/api/crop-health/predict${explain ? "?explain=true" : ""}`);
        request.upload.onprogress = (event) => {
          if (event.lengthComputable) setUploadProgress(Math.round((event.loaded / event.total) * 100));
        };
        request.onerror = () => reject(new Error("Could not reach the KrishiSaathi API. Check that the backend is running."));
        request.onload = () => {
          let response: Record<string, unknown>;
          try {
            response = JSON.parse(request.responseText) as Record<string, unknown>;
          } catch {
            reject(new Error("The API returned an invalid response."));
            return;
          }
          if (request.status < 200 || request.status >= 300) {
            reject(new Error(errorMessage(response, "The image could not be analyzed.")));
            return;
          }
          resolve(response);
        };
        request.send(body);
      });
      setPrediction({
        status: typeof data.status === "string" ? data.status : "unknown",
        disease: typeof data.disease === "string" ? data.disease : null,
        healthy: typeof data.healthy === "boolean" ? data.healthy : null,
        confidence: typeof data.confidence === "number" ? data.confidence : null,
        top_predictions: Array.isArray(data.top_predictions) ? (data.top_predictions as TopPrediction[]) : [],
        guidance: Array.isArray(data.guidance) ? data.guidance.filter((item): item is string => typeof item === "string") : [],
        message: typeof data.message === "string" ? data.message : "",
        threshold: typeof data.low_confidence_threshold === "number" ? data.low_confidence_threshold : 0.6,
        heatmap: typeof data.heatmap === "string" && /^data:image\/(jpeg|png);base64,/.test(data.heatmap) ? data.heatmap : null,
        evidence: typeof data.evidence === "string" ? data.evidence : null,
        reliability: data.reliability && typeof data.reliability === "object" ? (data.reliability as CropPrediction["reliability"]) : null,
      });
      await loadHistory();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not reach the KrishiSaathi API. Check that the backend is running.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="mx-auto max-w-3xl">
      <PageHeader title="Crop health">
        Photograph a single leaf and the model screens it for common diseases on 14 crops, reports how sure it is, and shows what it looked at.
      </PageHeader>

      <Notice tone="warning" className="mt-4" title="A screening aid, not a diagnosis">
        Confirm with your local agriculture officer or Krishi Vigyan Kendra before spraying or treating a crop. This app does not recommend pesticides or treatments.
      </Notice>

      <div
        className={`mt-6 rounded-2xl border-2 bg-white p-6 shadow-sm ${dragging ? "border-dashed border-green-600 bg-green-50" : "border-transparent ring-1 ring-slate-200"}`}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          choose(event.dataTransfer.files[0]);
        }}
      >
        <p className="flex items-center gap-2 text-sm text-slate-700">
          <UploadCloud size={18} aria-hidden="true" /> Choose an image or drag one into this area. JPG, PNG or WebP, up to {MAX_MB} MB.
        </p>
        <label htmlFor="crop-image" className="mt-4 block text-sm font-semibold text-slate-900">
          Crop image
        </label>
        <input
          ref={inputRef}
          id="crop-image"
          className="mt-2 block w-full rounded-lg border border-slate-400 bg-white p-3 text-sm"
          type="file"
          accept=".jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp"
          aria-describedby="crop-image-tips"
          onChange={(event) => choose(event.target.files?.[0])}
        />
        <p id="crop-image-tips" className="mt-2 text-xs leading-5 text-slate-600">
          Tips: one leaf, in focus, in even daylight, filling most of the frame. Supported crops: {SUPPORTED_CROPS}. Photos of other plants give unreliable results.
        </p>

        {file && preview && (
          <div className="mt-5 flex flex-col gap-4 sm:flex-row sm:items-start">
            <img src={preview} alt="Selected crop preview" className="max-h-64 rounded-xl border object-contain" />
            <div className="text-sm">
              <p className="break-all font-medium text-slate-900">{file.name}</p>
              <p className="text-slate-600">{formatSize(file.size)}</p>
              <button type="button" onClick={clearSelection} disabled={busy} className={`${buttonSecondary} mt-3`}>
                <Trash2 size={14} aria-hidden="true" /> Remove image
              </button>
            </div>
          </div>
        )}
        {error && (
          <Notice tone="warning" urgent className="mt-4">
            {error}
          </Notice>
        )}
        <label className="mt-4 flex items-start gap-2 text-sm text-slate-800">
          <input type="checkbox" checked={explain} onChange={(event) => setExplain(event.target.checked)} className="mt-1 h-4 w-4 accent-green-700" />
          <span>Show a heat-map of what the model looked at (takes about a second longer)</span>
        </label>
        <button disabled={!file || busy} onClick={submit} className={`${buttonPrimary} mt-5`}>
          <ImagePlus size={18} aria-hidden="true" /> {busy ? "Analyzing image…" : "Analyze image"}
        </button>
        {busy && (
          <p role="status" className="mt-3 text-sm text-slate-700">
            {uploadProgress < 100 ? `Uploading image… ${uploadProgress}%` : "Upload complete. Waiting for the model…"}
          </p>
        )}
      </div>

      {prediction && (
        <article role="status" className={`mt-5 rounded-2xl border p-5 ${resultStyle(prediction)}`}>
          <h2 className="text-lg font-semibold text-slate-900">{resultTitle(prediction)}</h2>
          <p className="mt-2">{prediction.message}</p>
          {prediction.evidence === "lab_only" && prediction.status === "diagnosed" && (
            <Notice tone="warning" className="mt-3">
              This class was learned from lab photos only and has not been tested on field photos, so treat this result with extra caution.
            </Notice>
          )}
          {prediction.heatmap && (
            <figure className="mt-3">
              <img src={prediction.heatmap} alt="Heat-map overlay on your photo: warmer colours mark the regions that influenced the model most" className="max-h-72 rounded-xl border" />
              <figcaption className="mt-1 text-xs leading-5 text-slate-700">
                Warmer areas pushed the model toward this answer. It shows what the model looked at, not whether it is right: if the highlight is on soil, a hand or the background rather than the leaf, distrust the result.
              </figcaption>
            </figure>
          )}
          {prediction.confidence !== null && (
            <div className="mt-2 text-sm text-slate-700">
              <p>Model score: {percent(prediction.confidence)} (not a calibrated probability)</p>
              <p className="mt-0.5">{scoreNote(prediction.confidence, prediction.threshold)}</p>
              {prediction.reliability && (
                <p className="mt-1 font-medium text-slate-900">
                  In field tests ({prediction.reliability.photos_tested} real photos), when the model answered with a score of at least {percent(prediction.reliability.score_at_least)}, it was right {percent(prediction.reliability.accuracy_when_answered)} of the time. That is a rough guide from a small test, not a guarantee for your leaf.
                </p>
              )}
            </div>
          )}
          {prediction.status === "diagnosed" && prediction.healthy && (
            <p className="mt-2 text-sm text-slate-800">
              &quot;Looks healthy&quot; only means the model did not match a disease it knows. It cannot see problems such as nutrient shortage, pests it was not trained on, or damage outside the leaf.
            </p>
          )}
          {prediction.top_predictions.length > 1 && (
            <div className="mt-3">
              <h3 className="text-sm font-semibold">Closest matches</h3>
              <ul className="mt-1 space-y-2 text-sm">
                {prediction.top_predictions.map((item) => (
                  <li key={item.label} className="grid grid-cols-[1fr_auto] items-center gap-x-3 gap-y-1 sm:grid-cols-[14rem_1fr_3.5rem]">
                    <span className="break-words" title={item.label}>
                      {item.label}
                    </span>
                    <span className="order-3 col-span-2 h-2 overflow-hidden rounded bg-white/80 ring-1 ring-slate-200 sm:order-none sm:col-span-1" aria-hidden="true">
                      <span className="block h-full bg-green-700" style={{ width: `${Math.round(item.confidence * 100)}%` }} />
                    </span>
                    <span className="text-right tabular-nums text-slate-700">{percent(item.confidence)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {prediction.guidance.length > 0 && (
            <ul className="mt-3 list-disc space-y-1 pl-5 text-sm leading-6">
              {prediction.guidance.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          )}
        </article>
      )}

      <details className="mt-8 rounded-xl border bg-white p-4 text-sm leading-6">
        <summary className="cursor-pointer text-base font-semibold text-slate-900">How reliable is this model?</summary>
        {modelInfo?.card?.metrics ? (
          <div className="mt-3 space-y-3 text-slate-800">
            {modelInfo.card.metrics.field_test && (
              <p>
                <strong>Real field photos ({modelInfo.card.metrics.field_test.dataset}, {modelInfo.card.metrics.field_test.n} photos not used for training):</strong> the right class{" "}
                {percent(modelInfo.card.metrics.field_test.top1)} of the time and the right crop {percent(modelInfo.card.metrics.field_test.crop_top1)}. The earlier lab-only model scored {percent(modelInfo.card.metrics.field_test.baseline_top1)} and {percent(modelInfo.card.metrics.field_test.baseline_crop_top1)}.
              </p>
            )}
            {modelInfo.card.metrics.lab_test && (
              <p>
                <strong>Clean lab photos ({modelInfo.card.metrics.lab_test.n}):</strong> {percent(modelInfo.card.metrics.lab_test.top1)} (before field tuning: {percent(modelInfo.card.metrics.lab_test.baseline_top1)}). Lab photos are far easier than a real field, so do not read this as field accuracy.
              </p>
            )}
            {modelInfo.card.metrics.non_leaf && (
              <p>
                <strong>Photos that are not leaves ({modelInfo.card.metrics.non_leaf.n}):</strong> {percent(modelInfo.card.metrics.non_leaf.shown_as_result)} still produced a confident result (before field tuning: {percent(modelInfo.card.metrics.non_leaf.baseline_shown_as_result)}).
              </p>
            )}
            {modelInfo.card.limitations && (
              <ul className="list-disc space-y-1 pl-5 text-slate-700">
                {modelInfo.card.limitations.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            )}
          </div>
        ) : (
          <p className="mt-3 text-slate-700">No evaluation report is available for the model currently loaded. Treat results as unverified.</p>
        )}
      </details>

      <h2 className="mt-8 text-xl font-semibold text-slate-900">Recent crop uploads</h2>
      <p className="mt-1 text-sm text-slate-600">Your last 50 uploads on this device&apos;s backend. Times are shown in your local time zone.</p>
      {historyLoading ? (
        <Loading>Loading crop history…</Loading>
      ) : historyError ? (
        <Notice tone="error" className="mt-3">
          {historyError}
        </Notice>
      ) : history.length ? (
        <ul className="mt-3 space-y-3">
          {history.map((item) => {
            const label = statusLabel[item.status] ?? { text: item.status.replace(/_/g, " "), tone: "slate" as const };
            return (
              <li key={item.id}>
                <article className="rounded-xl border bg-white p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <h3 className="break-all font-medium text-slate-900">{item.image_filename}</h3>
                    <Badge tone={label.tone}>{label.text}</Badge>
                  </div>
                  <p className="mt-1 text-sm text-slate-700">
                    {historySummary(item)}
                    {item.status === "diagnosed" && item.confidence !== null ? ` · score ${percent(item.confidence)}` : ""}
                  </p>
                  <time dateTime={item.created_at} className="mt-1 block text-xs text-slate-600">
                    {formatDateTime(item.created_at) || "Time unknown"}
                  </time>
                  {item.top_predictions && item.top_predictions.length > 0 && (
                    <details className="mt-2 text-sm">
                      <summary className="cursor-pointer font-medium text-green-800">Closest matches</summary>
                      <ul className="mt-1 space-y-0.5 pl-4">
                        {item.top_predictions.map((match) => (
                          <li key={match.label} className="list-disc">
                            {match.label} · {percent(match.confidence)}
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}
                </article>
              </li>
            );
          })}
        </ul>
      ) : (
        <div className="mt-3">
          <EmptyState title="No crop uploads yet.">Analyze a leaf photo above and it will appear here.</EmptyState>
        </div>
      )}
    </section>
  );
}
