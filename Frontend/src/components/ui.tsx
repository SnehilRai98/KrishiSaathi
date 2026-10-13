import type { ReactNode } from "react";
import { AlertCircle, CheckCircle2, Info, Loader2, TriangleAlert } from "lucide-react";

export function PageHeader({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <header>
      <h1 className="text-3xl font-bold text-slate-900">{title}</h1>
      {children && <p className="mt-2 max-w-3xl leading-7 text-slate-700">{children}</p>}
    </header>
  );
}

type Tone = "error" | "warning" | "success" | "info";

const toneStyles: Record<Tone, { box: string; icon: typeof Info }> = {
  error: { box: "border-red-200 bg-red-50 text-red-900", icon: AlertCircle },
  warning: { box: "border-amber-300 bg-amber-50 text-amber-950", icon: TriangleAlert },
  success: { box: "border-green-200 bg-green-50 text-green-950", icon: CheckCircle2 },
  info: { box: "border-blue-200 bg-blue-50 text-blue-950", icon: Info },
};

/** Inline message. Errors (or `urgent` ones) use role="alert"; everything else is announced politely. */
export function Notice({ tone, title, children, className = "", urgent = false }: { tone: Tone; title?: string; children: ReactNode; className?: string; urgent?: boolean }) {
  const { box, icon: Icon } = toneStyles[tone];
  return (
    <div role={tone === "error" || urgent ? "alert" : "status"} className={`flex gap-3 rounded-xl border p-4 text-sm leading-6 ${box} ${className}`}>
      <Icon size={18} aria-hidden="true" className="mt-0.5 shrink-0" />
      <div className="min-w-0">
        {title && <p className="font-semibold">{title}</p>}
        <div>{children}</div>
      </div>
    </div>
  );
}

export function Loading({ children }: { children: ReactNode }) {
  return (
    <p role="status" className="flex items-center justify-center gap-2 py-8 text-slate-600">
      <Loader2 size={18} aria-hidden="true" className="animate-spin motion-reduce:animate-none" />
      {children}
    </p>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-slate-300 bg-white p-6 text-center">
      <p className="font-semibold text-slate-800">{title}</p>
      {children && <div className="mt-1 text-sm text-slate-600">{children}</div>}
    </div>
  );
}

export function Badge({ tone = "slate", children }: { tone?: "green" | "amber" | "slate" | "blue" | "red"; children: ReactNode }) {
  const styles = {
    green: "bg-green-100 text-green-900",
    amber: "bg-amber-100 text-amber-950",
    slate: "bg-slate-100 text-slate-800",
    blue: "bg-blue-100 text-blue-900",
    red: "bg-red-100 text-red-900",
  };
  return <span className={`inline-flex items-center whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium ${styles[tone]}`}>{children}</span>;
}

export const buttonPrimary =
  "inline-flex items-center justify-center gap-2 rounded-lg bg-green-700 px-5 py-3 font-semibold text-white hover:bg-green-800 disabled:cursor-not-allowed disabled:opacity-50";
export const buttonSecondary =
  "inline-flex items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-800 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50";
export const inputClass = "mt-1 block w-full rounded-lg border border-slate-400 bg-white px-3 py-2 font-normal text-slate-900";

/** Label + control + hint + error wired together for screen readers. */
export function Field({
  id,
  label,
  hint,
  error,
  required,
  className = "",
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  error?: string;
  required?: boolean;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={className}>
      <label htmlFor={id} className="block text-sm font-semibold text-slate-900">
        {label}
        {required && <span className="text-red-700"> *</span>}
      </label>
      {children}
      {hint && (
        <p id={`${id}-hint`} className="mt-1 text-xs leading-5 text-slate-600">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} className="mt-1 text-xs font-medium text-red-800">
          {error}
        </p>
      )}
    </div>
  );
}
