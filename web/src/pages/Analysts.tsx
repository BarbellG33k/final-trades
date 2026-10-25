import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { get } from "../api/client";
import type { AnalystSummary, Page } from "../types";
import { DataTable, type Column } from "../components/DataTable";
import { Chip, ErrorState, Loading, Pagination, Panel, fmtPct, showLabel } from "../components/ui";

export default function AnalystsPage() {
  const [params, setParams] = useSearchParams();
  const page = Number(params.get("page") ?? 1);
  const { data, isPending, isError, error } = useQuery({
    queryKey: ["analysts", page],
    queryFn: () => get<Page<AnalystSummary>>("/analysts", { page, page_size: 30 }),
    placeholderData: (prev) => prev,
  });

  const cols: Column<AnalystSummary>[] = [
    { key: "name", header: "Analyst", cell: (a) => <Link className="lnk font-semibold" to={`/recommendations?analyst=${encodeURIComponent(a.canonical_name)}`}>{a.canonical_name}</Link> },
    { key: "aff", header: "Affiliation", cell: (a) => <span className="text-[var(--ink-soft)] max-w-[240px] truncate inline-block align-bottom" title={a.affiliation ?? ""}>{a.affiliation ?? "—"}</span> },
    { key: "count", header: "Recs", num: true, cell: (a) => a.recommendation_count },
    { key: "dist", header: "Shows", cell: (a) => Object.entries(a.show_distribution).map(([k, n]) => <Chip key={k} status="PENDING" label={`${showLabel(k)} ${n}`} />) },
    { key: "top", header: "Top instruments", cell: (a) => a.top_instruments.map(([sym, n]) => <Link key={sym} className="lnk font-num mr-2" to={`/recommendations?ticker=${encodeURIComponent(sym)}`}>{sym}<span className="text-[var(--ink-faint)]">×{n}</span></Link>) },
    { key: "verified", header: "Attribution verified", num: true, cell: (a) => fmtPct(a.attributed_share_verified, 0) },
    { key: "perf", header: "Perf. samples (1/5/20/60)", cell: (a) => a.insufficient_performance_data ? <span className="text-[var(--ink-faint)]">insufficient data</span> : <span className="font-num">{[1, 5, 20, 60].map((h) => a.performance_sample_sizes[h] ?? 0).join(" / ")}</span> },
  ];

  return (
    <Panel title="Analysts — no reliability ranking is published without sufficient observations and documented methodology">
      {isPending ? <Loading /> : isError ? <ErrorState message={(error as Error)?.message ?? "Failed"} /> : data ? (
        <>
          <DataTable rows={data.data} columns={cols} keyOf={(a) => a.id} emptyMessage="No analysts yet" />
          <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPage={(p) => setParams({ page: String(p) }, { replace: true })} />
        </>
      ) : null}
    </Panel>
  );
}
