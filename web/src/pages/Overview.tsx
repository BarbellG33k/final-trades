import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { get } from "../api/client";
import type { Overview, RecommendationRow } from "../types";
import { DataTable, type Column } from "../components/DataTable";
import { Chip, ErrorState, Loading, Panel, fmtDur, fmtNum, fmtPct, fmtTs, showLabel } from "../components/ui";

export default function OverviewPage() {
  const { data, isPending, error, isError, isPlaceholderData } = useQuery({
    queryKey: ["overview"],
    queryFn: () => get<Overview>("/overview"),
    refetchInterval: 60_000,
  });

  if (isPending) return <Loading rows={10} />;
  if (isError || !data) return <ErrorState message={(error as Error)?.message ?? "Failed to load"} />;

  const latest = data.latest_run;
  const recCols: Column<RecommendationRow>[] = [
    { key: "date", header: "Date", cell: (r) => <span className="font-num">{r.segment_date}</span> },
    { key: "show", header: "Show", cell: (r) => showLabel(r.show) },
    { key: "analyst", header: "Analyst", cell: (r) => r.analyst?.canonical_name ?? <em className="text-[var(--ink-faint)]">unattributed</em> },
    { key: "ticker", header: "Ticker", cell: (r) => <span className="font-num font-semibold">{r.instrument.symbol}</span> },
    { key: "dir", header: "Dir", cell: (r) => <Chip status={r.direction === "long" ? "OK" : r.direction === "short" ? "FAILED" : "PENDING"} label={r.direction} /> },
    { key: "ver", header: "Verification", cell: (r) => <Chip status={r.verification_status === "corroborated" || r.verification_status === "verified" ? "SUCCESS" : r.verification_status === "unresolved" ? "UNRESOLVED" : "PENDING"} label={r.verification_status} /> },
    {
      key: "link",
      header: "",
      cell: (r) => (
        <Link className="lnk" to={`/recommendations?focus=${r.id}`}>
          detail
        </Link>
      ),
    },
  ];

  return (
    <div className="space-y-3">
      {isPlaceholderData && <div className="micro text-[var(--warn)]">refreshing…</div>}
      {/* Status strip — compact, table-like, not hero cards */}
      <Panel>
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 divide-x divide-[var(--line)]">
          <Strip label="Latest run" value={latest ? <Link className="lnk" to={`/runs/${latest.id}`}>#{latest.id}</Link> : "—"} sub={latest ? <Chip status={latest.status} /> : undefined} />
          <Strip label="Started" value={<span className="font-num">{fmtTs(latest?.started_at)}</span>} sub={latest ? fmtDur(latest.duration_seconds) : undefined} />
          <Strip label="14d success" value={fmtPct(data.success_rate_14d, 0)} sub={`${data.runs_14d} runs`} />
          <Strip label="Backlog" value={fmtNum(data.backlog_remaining)} sub="dates outstanding" tone={data.backlog_remaining > 0 ? "warn" : undefined} />
          <Strip label="Created (run)" value={fmtNum(latest?.created_count)} sub={`${fmtNum(latest?.updated_count)} updated`} />
          <Strip label="Unresolved (run)" value={fmtNum(latest?.unresolved_count)} sub={`${fmtNum(latest?.rejected_count)} rejected`} tone={(latest?.unresolved_count ?? 0) > 0 ? "warn" : undefined} />
          <Strip label="Errors (run)" value={fmtNum(latest?.error_count)} sub={`${data.recent_failures.length} open issues`} tone={(latest?.error_count ?? 0) > 0 ? "bad" : undefined} />
          <Strip label="Records" value={fmtNum(data.totals.recommendations)} sub={`${fmtNum(data.totals.segments)} segments · ${fmtNum(data.totals.analysts)} analysts`} />
        </div>
      </Panel>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <Panel title="Per-show health (independent)">
          <table className="grid text-[12.5px]">
            <thead>
              <tr>
                <th>Show</th>
                <th>Last collected</th>
                <th className="num text-right">Recent recs (14d)</th>
                <th className="num text-right">Unresolved dates</th>
                <th className="num text-right">Failed dates</th>
                <th>Last success run</th>
              </tr>
            </thead>
            <tbody>
              {data.shows.map((s) => (
                <tr key={s.show}>
                  <td className="font-semibold">{showLabel(s.show)}</td>
                  <td className="font-num">{s.last_collected_date ?? <span className="text-[var(--bad)]">never</span>}</td>
                  <td className="num text-right font-num">{fmtNum(s.recent_recommendations)}</td>
                  <td className="num text-right font-num">{s.unresolved_dates > 0 ? <span className="text-[var(--warn)] font-semibold">{s.unresolved_dates}</span> : 0}</td>
                  <td className="num text-right font-num">{s.failed_dates > 0 ? <span className="text-[var(--bad)] font-semibold">{s.failed_dates}</span> : 0}</td>
                  <td>{s.last_success_run_id ? <Link className="lnk" to={`/runs/${s.last_success_run_id}`}>#{s.last_success_run_id}</Link> : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>

        <Panel title="Recent failures (open issues)" right={<Link className="lnk text-xs" to="/runs">runs →</Link>}>
          {data.recent_failures.length === 0 ? (
            <div className="p-3 text-[var(--ink-faint)] text-xs">No open issues 🎉</div>
          ) : (
            <table className="grid text-[12px]">
              <thead>
                <tr>
                  <th>Category</th>
                  <th>Show</th>
                  <th>Date</th>
                  <th>Summary</th>
                  <th className="num text-right">Attempts</th>
                  <th>Last seen</th>
                </tr>
              </thead>
              <tbody>
                {data.recent_failures.map((i) => (
                  <tr key={i.id}>
                    <td><Chip status="FAILED" label={i.error_category} /></td>
                    <td>{i.show_key ? showLabel(i.show_key) : "—"}</td>
                    <td className="font-num">{i.processing_date ?? "—"}</td>
                    <td className="max-w-[340px] truncate" title={i.summary}>{i.summary}</td>
                    <td className="num text-right font-num">{i.attempt_count}</td>
                    <td className="font-num">{fmtTs(i.last_occurred_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>
      </div>

      <Panel title="Most recent recommendations">
        <DataTable rows={data.newest_recommendations} columns={recCols} keyOf={(r) => r.id} emptyMessage="No recommendations collected yet" />
      </Panel>

      <p className="text-[11px] text-[var(--ink-faint)]">
        Window {data.window[0]} → {data.window[1]} · generated {fmtTs(data.generated_at)} ·
        collection is scheduled and read-only from this dashboard; failed dates are retried automatically by later runs.
      </p>
    </div>
  );
}

function Strip({ label, value, sub, tone }: { label: string; value: React.ReactNode; sub?: React.ReactNode; tone?: "warn" | "bad" }) {
  return (
    <div className="px-3 py-2">
      <div className="micro">{label}</div>
      <div className={`text-[15px] font-semibold mt-0.5 ${tone === "warn" ? "text-[var(--warn)]" : tone === "bad" ? "text-[var(--bad)]" : ""}`}>
        {value}
      </div>
      {sub && <div className="text-[11px] text-[var(--ink-faint)] mt-0.5">{sub}</div>}
    </div>
  );
}
