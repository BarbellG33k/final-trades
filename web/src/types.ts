// Mirror of the API schemas (src/final_trades/api/schemas.py).
// Keep in sync when the shared contract changes (AGENTS.md).

export interface Page<T> {
  data: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface RunSummary {
  id: number;
  trigger: string;
  status: "RUNNING" | "SUCCESS" | "PARTIAL_SUCCESS" | "FAILED";
  window_start: string | null;
  window_end: string | null;
  started_at: string;
  finished_at: string | null;
  duration_seconds: number | null;
  discovered_count: number;
  created_count: number;
  updated_count: number;
  rejected_count: number;
  unresolved_count: number;
  error_count: number;
  backlog_remaining: number | null;
  summary: string | null;
  per_show: Record<string, string>;
}

export interface SourceRunResult {
  source_key: string;
  show_key: string | null;
  status: string;
  items_discovered: number;
  items_processed: number;
  started_at: string | null;
  finished_at: string | null;
  error_category: string | null;
  error_summary: string | null;
}

export interface Issue {
  id: number;
  error_category: string;
  source_key: string | null;
  show_key: string | null;
  processing_date: string | null;
  stage: string;
  summary: string;
  first_occurred_at: string;
  last_occurred_at: string;
  occurrence_count: number;
  attempt_count: number;
  last_run_id: number | null;
  resolved: boolean;
  resolved_at: string | null;
}

export interface DateStatus {
  show: string;
  processing_date: string;
  status: string;
  is_trading_day: boolean | null;
  attempts: number;
  first_attempted_at: string | null;
  last_attempted_at: string | null;
  last_run_id: number | null;
  segment_id: number | null;
  note: string | null;
}

export interface RunDetail extends RunSummary {
  source_results: SourceRunResult[];
  issues: Issue[];
  date_results: DateStatus[];
}

export interface AnalystBrief {
  id: number;
  canonical_name: string;
  affiliation: string | null;
}

export interface InstrumentBrief {
  id: number;
  symbol: string;
  asset_type: string;
  name: string | null;
}

export interface RecommendationRow {
  id: number;
  segment_date: string;
  show: string;
  analyst: AnalystBrief | null;
  instrument: InstrumentBrief;
  direction: string;
  position_type: string;
  thesis: string | null;
  confidence: string;
  verification_status: string;
  extraction_method: string;
  published_at: string | null;
  source_urls: string[];
}

export interface Evidence {
  source_key: string;
  url: string;
  retrieved_at: string;
  published_at: string | null;
  content_sha256: string;
  excerpt: string;
  excerpt_kind: string;
}

export interface PerformanceObs {
  horizon_days: number;
  status: string;
  entry_date: string | null;
  entry_price: number | null;
  entry_basis: string | null;
  exit_date: string | null;
  exit_price: number | null;
  forward_return: number | null;
  benchmark_symbol: string | null;
  benchmark_return: number | null;
  relative_return: number | null;
  price_provider: string;
  computed_at: string;
}

export interface RecommendationDetail extends RecommendationRow {
  review_notes: string | null;
  analyst_title: string | null;
  evidence: Evidence[];
  performance: PerformanceObs[];
}

export interface HistoricalDateRow {
  the_date: string;
  show: string;
  status: string;
  coverage_status: string | null;
  recommendations_count: number;
  is_trading_day: boolean | null;
  attempts: number;
  note: string | null;
}

export interface AnalystSummary {
  id: number;
  canonical_name: string;
  affiliation: string | null;
  recommendation_count: number;
  show_distribution: Record<string, number>;
  top_instruments: [string, number][];
  attributed_share_verified: number | null;
  performance_sample_sizes: Record<number, number>;
  insufficient_performance_data: boolean;
}

export interface PerformanceSummaryRow {
  horizon_days: number;
  sample_size: number;
  missing_count: number;
  avg_forward_return: number | null;
  avg_benchmark_return: number | null;
  avg_relative_return: number | null;
  win_rate: number | null;
  short_sample_size: number;
  avg_short_relative_return: number | null;
}

export interface PerformanceSummary {
  benchmark_symbol: string;
  horizons: PerformanceSummaryRow[];
  methodology: string;
  disclaimer: string;
}

export interface ShowCoverage {
  show: string;
  total_dates: number;
  collected: number;
  verified_absent: number;
  partial: number;
  missing: number;
  unchecked: number;
  backlog: number;
  monthly: Record<string, number | string>[];
}

export interface Coverage {
  window_start: string;
  window_end: string;
  shows: ShowCoverage[];
  last_successful_check_by_source: Record<string, string | null>;
}

export interface OverviewShowStatus {
  show: string;
  last_collected_date: string | null;
  last_success_run_id: number | null;
  unresolved_dates: number;
  failed_dates: number;
  recent_recommendations: number;
}

export interface Overview {
  generated_at: string;
  window: [string, string];
  latest_run: RunSummary | null;
  last_successful_run: RunSummary | null;
  success_rate_14d: number | null;
  runs_14d: number;
  backlog_remaining: number;
  recent_failures: Issue[];
  shows: OverviewShowStatus[];
  newest_recommendations: RecommendationRow[];
  totals: Record<string, number>;
}
