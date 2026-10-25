import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import OverviewPage from "../pages/Overview";
import type { Overview } from "../types";

function wrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  );
}

const OVERVIEW: Overview = {
  generated_at: "2026-10-25T22:00:00Z",
  window: ["2025-10-25", "2026-10-25"],
  latest_run: {
    id: 42,
    trigger: "scheduled",
    status: "PARTIAL_SUCCESS",
    window_start: "2026-10-15",
    window_end: "2026-10-25",
    started_at: "2026-10-25T22:00:00Z",
    finished_at: "2026-10-25T22:01:30Z",
    duration_seconds: 90,
    discovered_count: 30,
    created_count: 7,
    updated_count: 2,
    rejected_count: 0,
    unresolved_count: 3,
    error_count: 1,
    backlog_remaining: 120,
    summary: "units=10 collected=6 failed=1 | halftime_report=0/1 fast_money=5/5",
    per_show: { halftime_report: "0/1", fast_money: "5/5" },
  },
  last_successful_run: null,
  success_rate_14d: 0.5,
  runs_14d: 8,
  backlog_remaining: 120,
  recent_failures: [
    {
      id: 1,
      error_category: "http_error",
      source_key: "benzinga_article",
      show_key: "halftime_report",
      processing_date: null,
      stage: "fetch",
      summary: "HTTP 500",
      first_occurred_at: "2026-10-25T22:00:10Z",
      last_occurred_at: "2026-10-25T22:00:10Z",
      occurrence_count: 1,
      attempt_count: 1,
      last_run_id: 42,
      resolved: false,
      resolved_at: null,
    },
  ],
  shows: [
    {
      show: "halftime_report",
      last_collected_date: null,
      last_success_run_id: null,
      unresolved_dates: 2,
      failed_dates: 1,
      recent_recommendations: 0,
    },
    {
      show: "fast_money",
      last_collected_date: "2026-10-23",
      last_success_run_id: 41,
      unresolved_dates: 0,
      failed_dates: 0,
      recent_recommendations: 16,
    },
  ],
  newest_recommendations: [
    {
      id: 5,
      segment_date: "2026-10-23",
      show: "fast_money",
      analyst: null,
      instrument: { id: 3, symbol: "NVDA", asset_type: "equity", name: null },
      direction: "long",
      position_type: "unknown",
      thesis: null,
      confidence: "medium",
      verification_status: "unverified",
      extraction_method: "cnbc_video_page",
      published_at: null,
      source_urls: ["https://www.cnbc.com/video/x.html"],
    },
  ],
  totals: { recommendations: 23, segments: 6, analysts: 5, instruments: 15, runs: 9 },
};

describe("Overview page", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, json: async () => OVERVIEW }),
    );
  });

  it("renders a failed show visibly next to a healthy one (scenario 18)", async () => {
    render(<OverviewPage />, { wrapper: wrapper() });
    await waitFor(() => expect(screen.getByText("PARTIAL_SUCCESS")).toBeInTheDocument());

    // per-show independence: Fast Money healthy, Halftime shows failure
    expect(screen.getAllByText("Halftime Report").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Fast Money").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("never")).toBeInTheDocument(); // Halftime never collected

    // open issue surfaces
    expect(screen.getByText("http_error")).toBeInTheDocument();
    expect(screen.getByText("HTTP 500")).toBeInTheDocument();

    // latest recommendations still render — dashboard usable despite failures
    expect(screen.getByText("NVDA")).toBeInTheDocument();
    expect(screen.getByText("unattributed")).toBeInTheDocument();
    vi.unstubAllGlobals();
  });

  it("shows backlog honestly", async () => {
    render(<OverviewPage />, { wrapper: wrapper() });
    await waitFor(() => expect(screen.getByText("120")).toBeInTheDocument());
    vi.unstubAllGlobals();
  });
});
