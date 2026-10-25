import { NavLink, Route, Routes } from "react-router-dom";
import OverviewPage from "./pages/Overview";
import RunsPage from "./pages/Runs";
import RunDetailPage from "./pages/RunDetail";
import RecommendationsPage from "./pages/Recommendations";
import HistoricalPage from "./pages/Historical";
import AnalystsPage from "./pages/Analysts";
import PerformancePage from "./pages/Performance";
import CoveragePage from "./pages/Coverage";

const TABS = [
  { to: "/", label: "Overview", end: true },
  { to: "/runs", label: "Runs" },
  { to: "/recommendations", label: "Recommendations" },
  { to: "/historical", label: "Historical Data" },
  { to: "/analysts", label: "Analysts" },
  { to: "/performance", label: "Performance" },
  { to: "/coverage", label: "Data Coverage" },
];

export default function App() {
  return (
    <div className="min-h-full flex flex-col">
      <header className="border-b border-[var(--line-strong)] bg-[var(--panel)] sticky top-0 z-20">
        <div className="px-3 pt-2 flex items-baseline gap-3">
          <h1 className="text-[15px] font-bold tracking-tight">
            Final Trade <span className="text-[var(--ink-faint)] font-medium">Intelligence</span>
          </h1>
          <span className="micro hidden sm:inline">
            CNBC Halftime Report · Fast Money — collected public segments
          </span>
        </div>
        <nav aria-label="Primary" className="px-2 flex gap-0.5 overflow-x-auto">
          {TABS.map((t) => (
            <NavLink
              key={t.to}
              to={t.to}
              end={t.end}
              className={({ isActive }) =>
                `px-3 py-1.5 text-[12.5px] font-semibold border-b-2 whitespace-nowrap ${
                  isActive
                    ? "border-[var(--accent)] text-[var(--accent)]"
                    : "border-transparent text-[var(--ink-soft)] hover:text-[var(--ink)]"
                }`
              }
            >
              {t.label}
            </NavLink>
          ))}
        </nav>
      </header>
      <main className="flex-1 p-3 max-w-[1800px] w-full mx-auto">
        <Routes>
          <Route path="/" element={<OverviewPage />} />
          <Route path="/runs" element={<RunsPage />} />
          <Route path="/runs/:runId" element={<RunDetailPage />} />
          <Route path="/recommendations" element={<RecommendationsPage />} />
          <Route path="/historical" element={<HistoricalPage />} />
          <Route path="/analysts" element={<AnalystsPage />} />
          <Route path="/performance" element={<PerformancePage />} />
          <Route path="/coverage" element={<CoveragePage />} />
          <Route path="*" element={<div className="p-6 text-[var(--ink-faint)]">Not found</div>} />
        </Routes>
      </main>
      <footer className="px-3 py-2 border-t border-[var(--line)] text-[11px] text-[var(--ink-faint)]">
        Independent open-source research project. Not affiliated with CNBC or NBCUniversal.
        Descriptive statistics only — not investment advice. Data shows gaps honestly; see Data Coverage.
      </footer>
    </div>
  );
}
