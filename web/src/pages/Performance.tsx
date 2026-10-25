import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { get } from "../api/client";
import type { Page, PerformanceSummary, RecommendationRow } from "../types";
import { DataTable, type Column } from "../components/DataTable";
import { Chip, ErrorState, Loading, Pagination, Panel, fmtPct, showLabel } from "../components/ui";

export default function PerformancePage() {
  const [params, setParams] = useSearchParams();
  const horizon = Number(params.get("horizon") ?? 20);
  const page = Number(params.get("page") ?? 1);

  const summary = useQuery({ queryKey: ["perf-summary"], queryFn: () => get<PerformanceSummary>("/performance/summary") });
  const rows = useQuery({
    queryKey: ["perf-recs", horizon, page],
    queryFn: () => get<Page<RecommendationRow>>("/performance/recommendations", { horizon, page, page_size: 25 }),
    placeholderData: (prev) => prev,
  });

  const cols: Column<RecommendationRow>[] = [
    { key: "date", header: "Date", cell: (r) => <span className="font-num">{r.segment_date}</span> },
    { key: "show", header: "Show", cell: (r) => showLabel(r.show) },
    { key: "analyst", header: "Analyst", cell: (r) => r.analyst?.canonical_name ?? <em className="text-[var(--ink-faint)]">unattributed</em> },
    { key: "ticker", header: "Ticker", cell: (r) => <span className="font-num font-bold">{r.instrument.symbol}</span> },
    { key: "dir", header: "Dir", cell: (r) => <Chip status={r.direction === "long" ? "OK" : r.direction === "short" ? "FAILED" : "PENDING"} label={r.direction} /> },
    { key: "src", header: "Source", cell: (r) => r.source_urls[0] ? <a className="lnk text-[11px] font-num" href={r.source_urls[0]} target="_blank" rel="noreferrer noopener">evidence ↗</a> : "—" },
  ];

  return (
    <div className="space-y-3">
      <Panel title={`Forward returns vs ${summary.data?.benchmark_symbol ?? "SPY"}`}>
        {summary.isPending ? <Loading rows={4} /> : summary.isError || !summary.data ? (
          <ErrorState message={(summary.error as Error)?.message ?? "Failed"} />
        ) : (
          <table className="grid">
            <thead>
              <tr>
                <th>Horizon</th><th className="num text-right">n (long)</th><th className="num text-right">Missing</th>
                <th className="num text-right">Avg return</th><th className="num text-right">Avg benchmark</th>
                <th className="num text-right">Avg relative</th><th className="num text-right">Beat rate</th>
                <th className="num text-right">n (short)</th><th className="num text-right">Short avg rel.</th>
              </tr>
            </thead>
            <tbody>
              {summary.data.horizons.map((h) => (
                <tr key={h.horizon_days}>
                  <td className="font-num font-semibold">{h.horizon_days} trading days</td>
                  <td className="num text-right font-num">{h.sample_size}</td>
                  <td className="num text-right font-num">{h.missing_count > 0 ? <span className="text-[var(--warn)]">{h.missing_count}</span> : 0}</td>
                  <td className="num text-right font-num">{fmtPct(h.avg_forward_return, 2)}</td>
                  <td className="num text-right font-num">{fmtPct(h.avg_benchmark_return, 2)}</td>
                  <td className={`num text-right font-num ${(h.avg_relative_return ?? 0) >= 0 ? "text-[var(--ok)]" : "text-[var(--bad)]"}`}>{fmtPct(h.avg_relative_return, 2)}</td>
                  <td className="num text-right font-num">{fmtPct(h.win_rate, 0)}</td>
                  <td className="num text-right font-num">{h.short_sample_size}</td>
                  <td className="num text-right font-num">{fmtPct(h.avg_short_relative_return, 2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {summary.data && (
          <div className="p-3 border-t border-[var(--line)] text-[11.5px] text-[var(--ink-soft)] space-y-1">
            <p><span className="micro mr-1">Methodology</span>{summary.data.methodology}</p>
            <p className="text-[var(--warn)]"><span className="micro mr-1">Disclaimer</span>{summary.data.disclaimer}</p>
          </div>
        )}
      </Panel>

      <Panel
        title="Measured recommendations"
        right={
          <select className="ctl" value={horizon} aria-label="Horizon"
            onChange={(e) => { const n = new URLSearchParams(params); n.set("horizon", e.target.value); n.set("page", "1"); setParams(n, { replace: true }); }}>
            {[1, 5, 20, 60].map((h) => <option key={h} value={h}>{h} trading days</option>)}
          </select>
        }
      >
        {rows.isPending ? <Loading /> : rows.isError ? <ErrorState message={(rows.error as Error)?.message ?? "Failed"} /> : rows.data ? (
          <>
            <DataTable rows={rows.data.data} columns={cols} keyOf={(r) => r.id} emptyMessage="No measured recommendations at this horizon yet" />
            <Pagination page={rows.data.page} pageSize={rows.data.page_size} total={rows.data.total} onPage={(p) => { const n = new URLSearchParams(params); n.set("page", String(p)); setParams(n, { replace: true }); }} />
          </>
        ) : null}
      </Panel>
    </div>
  );
}
