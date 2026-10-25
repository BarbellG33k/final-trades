import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { get } from "../api/client";
import type { Page, RecommendationDetail, RecommendationRow } from "../types";
import { DataTable, type Column } from "../components/DataTable";
import { Chip, ErrorState, Loading, Pagination, Panel, fmtPct, showLabel } from "../components/ui";

const PAGE_SIZE = 25;

const VERIFICATION_OPTIONS = ["verified", "corroborated", "unverified", "unresolved"];
const DIRECTION_OPTIONS = ["long", "short", "neutral", "mention"];
const METHOD_OPTIONS = ["benzinga_article", "cnbc_video_page", "cnbc_rss_title", "benzinga_listing_summary", "manual"];

export default function RecommendationsPage() {
  const [params, setParams] = useSearchParams();
  const [expandedId, setExpandedId] = useState<number | null>(() => {
    const focus = params.get("focus");
    return focus ? Number(focus) : null;
  });

  const q = {
    page: params.get("page") ?? "1",
    show: params.get("show") ?? "",
    ticker: params.get("ticker") ?? "",
    analyst: params.get("analyst") ?? "",
    direction: params.get("direction") ?? "",
    verification: params.get("verification") ?? "",
    extraction_method: params.get("extraction_method") ?? "",
    date_from: params.get("date_from") ?? "",
    date_to: params.get("date_to") ?? "",
    sort: params.get("sort") ?? "date_desc",
  };

  const { data, isPending, isError, error } = useQuery({
    queryKey: ["recommendations", q],
    queryFn: () =>
      get<Page<RecommendationRow>>("/recommendations", {
        page: q.page,
        page_size: PAGE_SIZE,
        show: q.show || null,
        ticker: q.ticker || null,
        analyst: q.analyst || null,
        direction: q.direction || null,
        verification: q.verification || null,
        extraction_method: q.extraction_method || null,
        date_from: q.date_from || null,
        date_to: q.date_to || null,
        sort: q.sort,
      }),
    placeholderData: (prev) => prev,
  });

  const detail = useQuery({
    queryKey: ["recommendation", expandedId],
    queryFn: () => get<RecommendationDetail>(`/recommendations/${expandedId}`),
    enabled: expandedId !== null,
  });

  const set = (k: string, v: string) => {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v);
    else next.delete(k);
    if (k !== "page") next.set("page", "1");
    setParams(next, { replace: true });
  };

  const cols: Column<RecommendationRow>[] = [
    { key: "exp", header: "", width: "24px", cell: (r) => <span className="text-[var(--ink-faint)]">{expandedId === r.id ? "▾" : "▸"}</span> },
    { key: "date", header: "Segment date", cell: (r) => <span className="font-num">{r.segment_date}</span> },
    { key: "show", header: "Show", cell: (r) => showLabel(r.show) },
    { key: "analyst", header: "Analyst", cell: (r) => r.analyst?.canonical_name ?? <em className="text-[var(--ink-faint)]">unattributed</em> },
    { key: "ticker", header: "Ticker", cell: (r) => <span className="font-num font-bold">{r.instrument.symbol}</span> },
    { key: "asset", header: "Asset", cell: (r) => r.instrument.asset_type },
    { key: "dir", header: "Dir", cell: (r) => <Chip status={r.direction === "long" ? "OK" : r.direction === "short" ? "FAILED" : "PENDING"} label={r.direction} /> },
    { key: "ver", header: "Verified", cell: (r) => <Chip status={r.verification_status === "unresolved" ? "UNRESOLVED" : r.verification_status === "unverified" ? "PENDING" : "SUCCESS"} label={r.verification_status} /> },
    { key: "method", header: "Method", cell: (r) => <span className="font-num text-[11px] text-[var(--ink-soft)]">{r.extraction_method}</span> },
    { key: "src", header: "Sources", num: true, cell: (r) => r.source_urls.length },
    { key: "thesis", header: "Thesis", cell: (r) => <span className="line-clamp-1 max-w-[420px] inline-block align-bottom text-[var(--ink-soft)]" title={r.thesis ?? ""}>{r.thesis ?? "—"}</span> },
  ];

  return (
    <Panel title="Recommendations">
      <div className="flex flex-wrap gap-2 items-end p-2 border-b border-[var(--line)] bg-[#fafbfc]">
        <Field label="From"><input type="date" className="ctl font-num" value={q.date_from} onChange={(e) => set("date_from", e.target.value)} /></Field>
        <Field label="To"><input type="date" className="ctl font-num" value={q.date_to} onChange={(e) => set("date_to", e.target.value)} /></Field>
        <Field label="Show">
          <select className="ctl" value={q.show} onChange={(e) => set("show", e.target.value)}>
            <option value="">all</option><option value="halftime_report">Halftime Report</option><option value="fast_money">Fast Money</option>
          </select>
        </Field>
        <Field label="Ticker"><input className="ctl w-20 font-num" value={q.ticker} placeholder="NVDA" onChange={(e) => set("ticker", e.target.value.toUpperCase())} /></Field>
        <Field label="Analyst"><input className="ctl w-32" value={q.analyst} placeholder="name contains" onChange={(e) => set("analyst", e.target.value)} /></Field>
        <Field label="Direction">
          <select className="ctl" value={q.direction} onChange={(e) => set("direction", e.target.value)}>
            <option value="">all</option>{DIRECTION_OPTIONS.map((d) => <option key={d}>{d}</option>)}
          </select>
        </Field>
        <Field label="Verification">
          <select className="ctl" value={q.verification} onChange={(e) => set("verification", e.target.value)}>
            <option value="">all</option>{VERIFICATION_OPTIONS.map((d) => <option key={d}>{d}</option>)}
          </select>
        </Field>
        <Field label="Method">
          <select className="ctl" value={q.extraction_method} onChange={(e) => set("extraction_method", e.target.value)}>
            <option value="">all</option>{METHOD_OPTIONS.map((d) => <option key={d}>{d}</option>)}
          </select>
        </Field>
        <Field label="Sort">
          <select className="ctl" value={q.sort} onChange={(e) => set("sort", e.target.value)}>
            <option value="date_desc">newest first</option><option value="date_asc">oldest first</option>
          </select>
        </Field>
      </div>

      {isPending ? (
        <Loading />
      ) : isError ? (
        <ErrorState message={(error as Error)?.message ?? "Failed to load"} />
      ) : data ? (
        <>
          <DataTable
            rows={data.data}
            columns={cols}
            keyOf={(r) => r.id}
            onRowClick={(r) => setExpandedId(expandedId === r.id ? null : r.id)}
            isExpanded={(r) => expandedId === r.id}
            renderExpanded={() => <ExpandedDetail query={detail} />}
            emptyMessage="No recommendations match these filters"
          />
          <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPage={(p) => set("page", String(p))} />
        </>
      ) : null}
    </Panel>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-0.5">
      <span className="micro">{label}</span>
      {children}
    </label>
  );
}

function ExpandedDetail({ query }: { query: ReturnType<typeof useQuery<RecommendationDetail>> }) {
  if (query.isPending) return <div className="p-3"><Loading rows={3} /></div>;
  if (query.isError || !query.data) return <ErrorState message={(query.error as Error)?.message ?? "Failed to load detail"} />;
  const d = query.data;
  return (
    <div className="p-3 grid grid-cols-1 lg:grid-cols-2 gap-3 text-[12px]">
      <div>
        <div className="micro mb-1">Evidence ({d.evidence.length})</div>
        <ul className="space-y-2">
          {d.evidence.map((e, i) => (
            <li key={i} className="border border-[var(--line)] rounded p-2 bg-white">
              <div className="flex gap-2 items-center flex-wrap">
                <Chip status="PENDING" label={e.source_key} />
                <a className="lnk font-num text-[11px] break-all" href={e.url} target="_blank" rel="noreferrer noopener">{e.url}</a>
              </div>
              <blockquote className="mt-1 pl-2 border-l-2 border-[var(--line-strong)] text-[var(--ink-soft)] italic">
                “{e.excerpt}”
              </blockquote>
              <div className="mt-1 text-[10.5px] text-[var(--ink-faint)] font-num">
                retrieved {new Date(e.retrieved_at).toISOString().slice(0, 16).replace("T", " ")}Z · sha256 {e.content_sha256.slice(0, 12)}…{e.content_sha256.slice(-6)}
              </div>
            </li>
          ))}
        </ul>
        {d.review_notes && (
          <div className="mt-2 p-2 rounded border border-[#fde68a] bg-[#fffbeb] text-[var(--warn)]">
            <span className="micro mr-1">Review note</span> {d.review_notes}
          </div>
        )}
        {d.analyst_title && <div className="mt-2 text-[var(--ink-soft)]"><span className="micro mr-1">Affiliation</span>{d.analyst_title}</div>}
      </div>
      <div>
        <div className="micro mb-1">Forward performance</div>
        {d.performance.length === 0 ? (
          <div className="text-[var(--ink-faint)]">No performance observations yet (computed nightly once price data is available).</div>
        ) : (
          <table className="grid">
            <thead><tr><th>Horizon</th><th className="num text-right">Entry</th><th className="num text-right">Exit</th><th className="num text-right">Return</th><th className="num text-right">vs {d.performance[0]?.benchmark_symbol ?? "SPY"}</th><th>Status</th></tr></thead>
            <tbody>
              {d.performance.map((p) => (
                <tr key={p.horizon_days}>
                  <td className="font-num">{p.horizon_days}td</td>
                  <td className="num text-right font-num">{p.entry_price?.toFixed(2) ?? "—"} <span className="text-[var(--ink-faint)]">{p.entry_date ?? ""}</span></td>
                  <td className="num text-right font-num">{p.exit_price?.toFixed(2) ?? "—"} <span className="text-[var(--ink-faint)]">{p.exit_date ?? ""}</span></td>
                  <td className="num text-right font-num">{fmtPct(p.forward_return, 2)}</td>
                  <td className={`num text-right font-num ${(p.relative_return ?? 0) >= 0 ? "text-[var(--ok)]" : "text-[var(--bad)]"}`}>{fmtPct(p.relative_return, 2)}</td>
                  <td><Chip status={p.status === "OK" ? "SUCCESS" : "PENDING"} label={p.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
