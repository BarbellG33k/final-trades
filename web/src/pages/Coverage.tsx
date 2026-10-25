import { useQuery } from "@tanstack/react-query";
import { get } from "../api/client";
import type { Coverage } from "../types";
import { Chip, ErrorState, Loading, Panel, fmtTs, showLabel } from "../components/ui";

export default function CoveragePage() {
  const { data, isPending, isError, error } = useQuery({
    queryKey: ["coverage"],
    queryFn: () => get<Coverage>("/coverage"),
  });

  if (isPending) return <Loading rows={10} />;
  if (isError || !data) return <ErrorState message={(error as Error)?.message ?? "Failed"} />;

  const maxTotal = Math.max(1, ...data.shows.map((s) => s.total_dates));

  return (
    <div className="space-y-3">
      <Panel title={`Collection window ${data.window_start} → ${data.window_end}`}>
        <table className="grid">
          <thead>
            <tr>
              <th>Show</th><th className="num text-right">Dates</th><th className="num text-right">Collected</th>
              <th className="num text-right">Verified absent</th><th className="num text-right">Partial</th>
              <th className="num text-right">Missing/failed</th><th className="num text-right">Unchecked</th>
              <th className="num text-right">Backlog</th><th style={{ width: "26%" }}>Completeness</th>
            </tr>
          </thead>
          <tbody>
            {data.shows.map((s) => {
              const trading = s.total_dates - s.verified_absent;
              const pct = trading > 0 ? s.collected / trading : 0;
              return (
                <tr key={s.show}>
                  <td className="font-semibold">{showLabel(s.show)}</td>
                  <td className="num text-right font-num">{s.total_dates}</td>
                  <td className="num text-right font-num text-[var(--ok)] font-semibold">{s.collected}</td>
                  <td className="num text-right font-num">{s.verified_absent}</td>
                  <td className="num text-right font-num">{s.partial > 0 ? <span className="text-[var(--warn)]">{s.partial}</span> : 0}</td>
                  <td className="num text-right font-num">{s.missing > 0 ? <span className="text-[var(--bad)] font-semibold">{s.missing}</span> : 0}</td>
                  <td className="num text-right font-num">{s.unchecked > 0 ? <span className="text-[var(--ink-faint)]">{s.unchecked}</span> : 0}</td>
                  <td className="num text-right font-num">{s.backlog}</td>
                  <td>
                    <div className="h-2.5 w-full bg-[#eceef2] rounded-sm overflow-hidden" role="img" aria-label={`${Math.round(pct * 100)}% of trading days collected`}>
                      <div className="h-full bg-[var(--ok)]" style={{ width: `${Math.min(100, pct * 100)}%` }} />
                    </div>
                    <div className="text-[10.5px] font-num text-[var(--ink-faint)] mt-0.5">{Math.round(pct * 100)}% of {trading} trading days</div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <div className="px-3 py-1.5 text-[11px] text-[var(--ink-faint)] border-t border-[var(--line)]">
          Scale note: {maxTotal} date rows tracked per show. An attractive dashboard must not conceal missing
          data — every gap above is either verified absence (non-trading day) or an honest, retrying backlog entry.
        </div>
      </Panel>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
        {data.shows.map((s) => (
          <Panel key={s.show} title={`Monthly coverage — ${showLabel(s.show)}`}>
            {s.monthly.length === 0 ? (
              <div className="p-3 text-[var(--ink-faint)] text-xs">No coverage rows yet.</div>
            ) : (
              <table className="grid">
                <thead><tr><th>Month</th>{Object.keys(s.monthly[0]).filter((k) => k !== "month").map((k) => <th key={k} className="num text-right">{k}</th>)}</tr></thead>
                <tbody>
                  {s.monthly.map((m) => (
                    <tr key={String(m.month)}>
                      <td className="font-num">{String(m.month)}</td>
                      {Object.keys(s.monthly[0]).filter((k) => k !== "month").map((k) => (
                        <td key={k} className="num text-right font-num">{String(m[k] ?? 0)}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Panel>
        ))}
      </div>

      <Panel title="Last successful check by source">
        <table className="grid">
          <thead><tr><th>Source</th><th>Last success</th><th>Health</th></tr></thead>
          <tbody>
            {Object.entries(data.last_successful_check_by_source).map(([src, ts]) => (
              <tr key={src}>
                <td className="font-num">{src}</td>
                <td className="font-num">{fmtTs(ts)}</td>
                <td>{ts ? <Chip status="SUCCESS" label="ok" /> : <Chip status="FAILED" label="never succeeded" />}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </div>
  );
}
