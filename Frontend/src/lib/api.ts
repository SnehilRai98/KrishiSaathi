/** Base URL of the backend API (override with VITE_API_URL in Frontend/.env). */
export const API = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/+$/, "") || "http://127.0.0.1:8000";

/** Read a FastAPI error body (string or validation list) into a readable message. */
export function errorMessage(body: unknown, fallback: string): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const text = detail
      .map((issue: { loc?: (string | number)[]; msg?: string }) => `${issue.loc?.[issue.loc.length - 1] ?? "input"}: ${issue.msg ?? "Invalid value"}`)
      .join("; ");
    if (text) return text;
  }
  const nested = (detail as { database?: { error?: string } } | undefined)?.database?.error;
  return nested || fallback;
}

/** "12 Oct 2026, 3:45 pm" in the viewer's local time; empty string if the value is unusable. */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString(undefined, { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" });
}

/** "10 Oct 2026" for a YYYY-MM-DD string (no time-zone shifting). */
export function formatDate(isoDate: string | null | undefined): string {
  if (!isoDate) return "";
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoDate);
  if (!match) return isoDate;
  const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  return date.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}
