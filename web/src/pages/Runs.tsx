import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { get } from "../api/client";
import type { Page, RunSummary } from "../types";
import { DataTable, type Column } from "../components/DataTable";
import { Chip, ErrorState, Loading, Pagination, Panel, fmtDur, fmtNum, fmtTs } from "../components/ui";

const PAGE_SIZE = 20;

export default function RunsPage() {
  const [params, setParams] = useSearchParams();
  const page = Number(params.get("page") ?? 1);
  const status = params.get("status") ?? "";
  const trigger = params.get("trigger") ?? "";

  const { data, isPending, isError, error } = useQuery({
    queryKey: ["runs", page, status, trigger],
    queryFn: () =>
      get<Page<RunSummary>>("/runs", { page, page_size: PAGE_SIZE, status: status || null, trigger: trigger || null }),
    placeholderData: (prev) => prev,
  });

  const set = (k: string, v: string) => {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v);
    else next.delete(k);
    if (k !== "page") next.set("page", "1");
    setParams(next, { replace: true });
  };

  const cols: Column<RunSummary>[] = [
    { key: "id", header: "Run", cell: (r) => <Link className="lnk font-num" to={`/runs/${r.id}`}>#{r.id}</Link> },
    { key: "trigger", header: "Trigger", cell: (r) => <Chip status="PENDING" label={r.trigger} /> },
    { key: "window", header: "Window", cell: (r) => <span className="font-num">{r.window_start} → {r.window_end}</span> },
    { key: "started", header: "Started", cell: (r) => <span className="font-num">{fmtTs(r.started_at)}</span> },
    { key: "dur", header: "Duration", num: true, cell: (r) => fmtDur(r.duration_seconds) },
    { key: "status", header: "Status", cell: (r) => <Chip status={r.status} /> },
    { key: "hr", header: "Halftime", cell: (r) => <ShowCell value={r.per_show.halftime_report} /> },
    { key: "fm", header: "Fast Money", cell: (r) => <ShowCell value={r.per_show.fast_money} /> },
    { key: "disc", header: "Disc.", num: true, cell: (r) => fmtNum(r.discovered_count) },
    { key: "new", header: "New", num: true, cell: (r) => fmtNum(r.created_count) },
    { key: "upd", header: "Upd.", num: true, cell: (r) => fmtNum(r.updated_count) },
    { key: "unres", header: "Unres.", num: true, cell: (r) => (r.unresolved_count > 0 ? <span className="text-[var(--warn)]">{r.unresolved_count}</span> : 0) },
    { key: "err", header: "Errs", num: true, cell: (r) => (r.error_count > 0 ? <span className="text-[var(--bad)]">{r.error_count}</span> : 0) },
    { key: "summary", header: "Summary", cell: (r) => <span className="text-[var(--ink-soft)] line-clamp-1 max-w-[380px] inline-block align-bottom" title={r.summary ?? ""}>{r.summary}</span> },
  ];

  return (
    <Panel
      title="Ingestion runs"
      right={
        <div className="flex gap-2 items-center">
          <select className="ctl" value={status} onChange={(e) => set("status", e.target.value)} aria-label="Filter status">
            <option value="">all statuses</option>
            {["RUNNING", "SUCCESS", "PARTIAL_SUCCESS", "FAILED"].map((s) => <option key={s}>{s}</option>)}
          </select>
          <select className="ctl" value={trigger} onChange={(e) => set("trigger", e.target.value)} aria-label="Filter trigger">
            <option value="">all triggers</option>
            {["scheduled", "backfill", "manual"].map((s) => <option key={s}>{s}</option>)}
          </select>
        </div>
      }
    >
      {isPending ? (
        <Loading />
      ) : isError ? (
        <ErrorState message={(error as Error)?.message ?? "Failed to load runs"} />
      ) : data ? (
        <>
          <DataTable rows={data.data} columns={cols} keyOf={(r) => r.id} emptyMessage="No runs recorded yet" />
          <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPage={(p) => set("page", String(p))} />
        </>
      ) : null}
    </Panel>
  );
}

function ShowCell({ value }: { value?: string }) {
  if (!value) return <span className="text-[var(--ink-faint)]">—</span>;
  const [ok, total] = value.split("/");
  const healthy = ok === total;
  return (
    <span className={`font-num ${healthy ? "" : "text-[var(--warn)] font-semibold"}`}>{value}</span>
  );
}
