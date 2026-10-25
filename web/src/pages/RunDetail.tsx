import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { get } from "../api/client";
import type { DateStatus, Issue, RunDetail, SourceRunResult } from "../types";
import { DataTable, type Column } from "../components/DataTable";
import { Chip, ErrorState, Loading, Panel, fmtDur, fmtNum, fmtTs, showLabel } from "../components/ui";

export default function RunDetailPage() {
  const { runId } = useParams();
  const { data, isPending, isError, error } = useQuery({
    queryKey: ["run", runId],
    queryFn: () => get<RunDetail>(`/runs/${runId}`),
    enabled: Boolean(runId),
  });

  if (isPending) return <Loading rows={12} />;
  if (isError || !data) return <ErrorState message={(error as Error)?.message ?? "Failed to load run"} />;

  const sourceCols: Column<SourceRunResult>[] = [
    { key: "src", header: "Source", cell: (s) => <span className="font-num">{s.source_key}</span> },
    { key: "show", header: "Show", cell: (s) => (s.show_key ? showLabel(s.show_key) : "—") },
    { key: "status", header: "Outcome", cell: (s) => <Chip status={s.status === "SUCCESS" ? "SUCCESS" : s.status === "PARTIAL" ? "PARTIAL_SUCCESS" : "FAILED"} label={s.status} /> },
    { key: "disc", header: "Discovered", num: true, cell: (s) => fmtNum(s.items_discovered) },
    { key: "proc", header: "Processed", num: true, cell: (s) => fmtNum(s.items_processed) },
    { key: "err", header: "Error", cell: (s) => (s.error_summary ? <span className="text-[var(--bad)]">{s.error_category}: {s.error_summary}</span> : "—") },
    { key: "fin", header: "Finished", cell: (s) => <span className="font-num">{fmtTs(s.finished_at)}</span> },
  ];

  const dateCols: Column<DateStatus>[] = [
    { key: "date", header: "Date", cell: (d) => <span className="font-num">{d.processing_date}</span> },
    { key: "show", header: "Show", cell: (d) => showLabel(d.show) },
    { key: "status", header: "Result", cell: (d) => <Chip status={d.status} /> },
    { key: "attempts", header: "Attempts", num: true, cell: (d) => d.attempts },
    { key: "segment", header: "Segment", cell: (d) => (d.segment_id ? <span className="font-num">#{d.segment_id}</span> : "—") },
    { key: "note", header: "Note", cell: (d) => <span className="text-[var(--ink-soft)] line-clamp-1 max-w-[420px] inline-block align-bottom" title={d.note ?? ""}>{d.note ?? "—"}</span> },
  ];

  const issueCols: Column<Issue>[] = [
    { key: "cat", header: "Category", cell: (i) => <Chip status="FAILED" label={i.error_category} /> },
    { key: "stage", header: "Stage", cell: (i) => i.stage },
    { key: "show", header: "Show", cell: (i) => (i.show_key ? showLabel(i.show_key) : "—") },
    { key: "date", header: "Date", cell: (i) => <span className="font-num">{i.processing_date ?? "—"}</span> },
    { key: "summary", header: "Summary", cell: (i) => <span className="line-clamp-1 max-w-[420px] inline-block align-bottom" title={i.summary}>{i.summary}</span> },
    { key: "count", header: "Occurrences", num: true, cell: (i) => i.occurrence_count },
    { key: "resolved", header: "State", cell: (i) => (i.resolved ? <Chip status="SUCCESS" label="resolved" /> : <Chip status="FAILED" label="open" />) },
  ];

  return (
    <div className="space-y-3">
      <Panel>
        <div className="p-3 flex flex-wrap items-center gap-x-6 gap-y-2">
          <div>
            <div className="micro">Run</div>
            <div className="text-lg font-bold font-num">#{data.id} <Chip status={data.status} /></div>
          </div>
          <KV k="Trigger" v={data.trigger} />
          <KV k="Window" v={<span className="font-num">{data.window_start} → {data.window_end}</span>} />
          <KV k="Started" v={<span className="font-num">{fmtTs(data.started_at)}</span>} />
          <KV k="Finished" v={<span className="font-num">{fmtTs(data.finished_at)}</span>} />
          <KV k="Duration" v={fmtDur(data.duration_seconds)} />
          <KV k="Discovered" v={fmtNum(data.discovered_count)} />
          <KV k="Created" v={fmtNum(data.created_count)} />
          <KV k="Updated" v={fmtNum(data.updated_count)} />
          <KV k="Rejected" v={fmtNum(data.rejected_count)} />
          <KV k="Unresolved" v={fmtNum(data.unresolved_count)} warn={data.unresolved_count > 0} />
          <KV k="Errors" v={fmtNum(data.error_count)} bad={data.error_count > 0} />
          <KV k="Backlog left" v={fmtNum(data.backlog_remaining)} />
          {Object.entries(data.per_show).map(([show, v]) => (
            <KV key={show} k={showLabel(show)} v={<span className="font-num">{v}</span>} />
          ))}
        </div>
        {data.summary && (
          <div className="px-3 pb-2 text-xs text-[var(--ink-soft)] font-num">{data.summary}</div>
        )}
        <div className="px-3 pb-2">
          <Link className="lnk text-xs" to="/runs">← all runs</Link>
        </div>
      </Panel>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
        <Panel title="Sources checked">
          <DataTable rows={data.source_results} columns={sourceCols} keyOf={(s) => `${s.source_key}-${s.started_at}`} emptyMessage="No source results recorded" />
        </Panel>
        <Panel title={`Errors & issues (${data.issues.length})`}>
          <DataTable rows={data.issues} columns={issueCols} keyOf={(i) => i.id} emptyMessage="No errors recorded for this run" />
        </Panel>
      </div>

      <Panel title={`Dates processed in this run (${data.date_results.length})`}>
        <DataTable rows={data.date_results} columns={dateCols} keyOf={(d) => `${d.show}-${d.processing_date}`} emptyMessage="No date units processed" />
      </Panel>
    </div>
  );
}

function KV({ k, v, warn, bad }: { k: string; v: React.ReactNode; warn?: boolean; bad?: boolean }) {
  return (
    <div>
      <div className="micro">{k}</div>
      <div className={`text-[13px] font-semibold ${warn ? "text-[var(--warn)]" : bad ? "text-[var(--bad)]" : ""}`}>{v}</div>
    </div>
  );
}
