// Shared presentational primitives for the dense dashboard.

import type { ReactNode } from "react";

export type Tone = "ok" | "warn" | "bad" | "neutral" | "accent";

export function toneForStatus(status: string): Tone {
  switch (status) {
    case "SUCCESS":
    case "COLLECTED":
    case "COMPLETE":
    case "NO_SEGMENT":
    case "VERIFIED_ABSENT":
    case "OK":
      return "ok";
    case "PARTIAL_SUCCESS":
    case "PARTIAL":
    case "UNRESOLVED":
    case "MISSING":
    case "NOT_DUE":
      return "warn";
    case "FAILED":
      return "bad";
    case "RUNNING":
      return "accent";
    default:
      return "neutral";
  }
}

export function Chip({ status, label }: { status: string; label?: string }) {
  const tone = toneForStatus(status);
  return <span className={`chip chip-${tone}`}>{label ?? status}</span>;
}

export function Panel({
  title,
  right,
  children,
  className = "",
}: {
  title?: ReactNode;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel ${className}`}>
      {(title || right) && (
        <header className="panel-head">
          <div className="micro">{title}</div>
          {right}
        </header>
      )}
      {children}
    </section>
  );
}

export function Loading({ rows = 6 }: { rows?: number }) {
  return (
    <div className="p-2 space-y-1.5" role="status" aria-label="Loading">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="skeleton h-4" style={{ width: `${95 - (i % 4) * 12}%` }} />
      ))}
    </div>
  );
}

export function EmptyState({ message }: { message: string }) {
  return (
    <div className="p-6 text-center text-[var(--ink-faint)]" role="status">
      {message}
    </div>
  );
}

export function ErrorState({ message, stale }: { message: string; stale?: boolean }) {
  return (
    <div className="p-4 text-[var(--bad)]" role="alert">
      {stale && <span className="chip chip-warn mr-2">stale</span>}
      {message}
    </div>
  );
}

export function fmtPct(x: number | null | undefined, digits = 1): string {
  if (x === null || x === undefined) return "—";
  return `${(x * 100).toFixed(digits)}%`;
}

export function fmtNum(x: number | null | undefined): string {
  if (x === null || x === undefined) return "—";
  return x.toLocaleString("en-US");
}

export function fmtDur(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}m${String(s).padStart(2, "0")}s`;
}

export function fmtTs(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toISOString().slice(0, 16).replace("T", " ") + "Z";
}

export function Pagination({
  page,
  pageSize,
  total,
  onPage,
}: {
  page: number;
  pageSize: number;
  total: number;
  onPage: (p: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div className="flex items-center gap-2 px-2 py-1.5 border-t border-[var(--line)] text-xs">
      <button className="ctl" disabled={page <= 1} onClick={() => onPage(page - 1)}>
        ← Prev
      </button>
      <span className="font-num text-[var(--ink-soft)]">
        p.{page}/{pages} · {total.toLocaleString("en-US")} rows
      </span>
      <button className="ctl" disabled={page >= pages} onClick={() => onPage(page + 1)}>
        Next →
      </button>
    </div>
  );
}

export function showLabel(key: string): string {
  return key === "fast_money" ? "Fast Money" : key === "halftime_report" ? "Halftime Report" : key;
}
