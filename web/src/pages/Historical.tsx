import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { get } from "../api/client";
import type { HistoricalDateRow, Page } from "../types";
import { DataTable, type Column } from "../components/DataTable";
import { Chip, ErrorState, Loading, Pagination, Panel, showLabel } from "../components/ui";

const PAGE_SIZE = 40;

export default function HistoricalPage() {
  const [params, setParams] = useSearchParams();
  const q = {
    page: params.get("page") ?? "1",
    show: params.get("show") ?? "",
    status: params.get("status") ?? "",
    date_from: params.get("date_from") ?? "",
    date_to: params.get("date_to") ?? "",
  };
  const { data, isPending, isError, error } = useQuery({
    queryKey: ["historical", q],
    queryFn: () =>
      get<Page<HistoricalDateRow>>("/historical/dates", {
        page: q.page,
        page_size: PAGE_SIZE,
        show: q.show || null,
        status: q.status || null,
        date_from: q.date_from || null,
        date_to: q.date_to || null,
      }),
    placeholderData: (prev) => prev,
  });

  const set = (k: string, v: string) => {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v);
    else next.delete(k);
    if (k !== "page") next.set("page", "1");
    setParams(next, { replace: true });
  };

  const cols: Column<HistoricalDateRow>[] = [
    { key: "date", header: "Date", cell: (r) => <span className="font-num">{r.the_date}</span> },
    { key: "show", header: "Show", cell: (r) => showLabel(r.show) },
    { key: "trading", header: "Trading day", cell: (r) => (r.is_trading_day ? "yes" : <span className="text-[var(--ink-faint)]">no</span>) },
    { key: "status", header: "Processing", cell: (r) => <Chip status={r.status} /> },
    { key: "cov", header: "Coverage", cell: (r) => (r.coverage_status ? <Chip status={r.coverage_status === "COMPLETE" ? "SUCCESS" : r.coverage_status === "MISSING" ? "FAILED" : r.coverage_status === "PARTIAL" ? "PARTIAL_SUCCESS" : "PENDING"} label={r.coverage_status} /> : "—") },
    { key: "recs", header: "Recs", num: true, cell: (r) => r.recommendations_count },
    { key: "attempts", header: "Attempts", num: true, cell: (r) => r.attempts },
    { key: "note", header: "Note", cell: (r) => <span className="line-clamp-1 max-w-[420px] inline-block align-bottom text-[var(--ink-soft)]" title={r.note ?? ""}>{r.note ?? "—"}</span> },
  ];

  return (
    <Panel title="Historical date-by-date processing state">
      <div className="flex flex-wrap gap-2 items-end p-2 border-b border-[var(--line)] bg-[#fafbfc]">
        <label className="flex flex-col gap-0.5"><span className="micro">From</span>
          <input type="date" className="ctl font-num" value={q.date_from} onChange={(e) => set("date_from", e.target.value)} /></label>
        <label className="flex flex-col gap-0.5"><span className="micro">To</span>
          <input type="date" className="ctl font-num" value={q.date_to} onChange={(e) => set("date_to", e.target.value)} /></label>
        <label className="flex flex-col gap-0.5"><span className="micro">Show</span>
          <select className="ctl" value={q.show} onChange={(e) => set("show", e.target.value)}>
            <option value="">both</option><option value="halftime_report">Halftime Report</option><option value="fast_money">Fast Money</option>
          </select></label>
        <label className="flex flex-col gap-0.5"><span className="micro">Status</span>
          <select className="ctl" value={q.status} onChange={(e) => set("status", e.target.value)}>
            <option value="">all</option>
            {["COLLECTED", "PENDING", "FAILED", "UNRESOLVED", "NO_SEGMENT"].map((s) => <option key={s}>{s}</option>)}
          </select></label>
        <p className="text-[11px] text-[var(--ink-faint)] max-w-md self-center">
          NO_SEGMENT = verified non-trading day. PENDING = not yet attempted. FAILED/UNRESOLVED =
          attempted, outstanding; later scheduled runs retry automatically.
        </p>
      </div>
      {isPending ? <Loading /> : isError ? <ErrorState message={(error as Error)?.message ?? "Failed"} /> : data ? (
        <>
          <DataTable rows={data.data} columns={cols} keyOf={(r) => `${r.show}-${r.the_date}`} emptyMessage="No dates in range" />
          <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPage={(p) => set("page", String(p))} />
        </>
      ) : null}
    </Panel>
  );
}
