import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Chip, Pagination, toneForStatus, fmtDur, fmtPct, showLabel } from "../components/ui";

describe("toneForStatus", () => {
  it("maps run statuses to distinct tones — partial never looks like success", () => {
    expect(toneForStatus("SUCCESS")).toBe("ok");
    expect(toneForStatus("COLLECTED")).toBe("ok");
    expect(toneForStatus("PARTIAL_SUCCESS")).toBe("warn");
    expect(toneForStatus("UNRESOLVED")).toBe("warn");
    expect(toneForStatus("FAILED")).toBe("bad");
    expect(toneForStatus("RUNNING")).toBe("accent");
    expect(toneForStatus("NO_SEGMENT")).toBe("ok");
    expect(toneForStatus("PENDING")).toBe("neutral");
  });
});

describe("Chip", () => {
  it("renders status text with the right tone class", () => {
    render(<Chip status="PARTIAL_SUCCESS" />);
    const el = screen.getByText("PARTIAL_SUCCESS");
    expect(el.className).toContain("chip-warn");
  });
  it("supports a custom label", () => {
    render(<Chip status="FAILED" label="blocked" />);
    expect(screen.getByText("blocked")).toBeInTheDocument();
  });
});

describe("Pagination", () => {
  it("disables prev on first page and next on last", () => {
    render(<Pagination page={1} pageSize={20} total={45} onPage={() => {}} />);
    expect(screen.getByText("← Prev")).toBeDisabled();
    expect(screen.getByText("Next →")).toBeEnabled();
    expect(screen.getByText(/3 rows|45 rows/)).toBeInTheDocument();
  });
  it("calls onPage with next page", async () => {
    const onPage = vi.fn();
    render(<Pagination page={2} pageSize={20} total={100} onPage={onPage} />);
    await userEvent.click(screen.getByText("Next →"));
    expect(onPage).toHaveBeenCalledWith(3);
  });
});

describe("formatters", () => {
  it("formats percents, durations, and show labels", () => {
    expect(fmtPct(0.1234, 2)).toBe("12.34%");
    expect(fmtPct(null)).toBe("—");
    expect(fmtDur(45.2)).toBe("45.2s");
    expect(fmtDur(125)).toBe("2m05s");
    expect(fmtDur(null)).toBe("—");
    expect(showLabel("fast_money")).toBe("Fast Money");
    expect(showLabel("halftime_report")).toBe("Halftime Report");
  });
});

describe("api client", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("throws ApiError with the generic envelope on failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 404,
        json: async () => ({ error: "not_found", message: "Run not found" }),
      }),
    );
    const { get, ApiError } = await import("../api/client");
    await expect(get("/runs/999")).rejects.toMatchObject({ status: 404, code: "not_found" });
    try {
      await get("/runs/999");
    } catch (e) {
      expect(e).toBeInstanceOf(ApiError);
    }
    vi.unstubAllGlobals();
  });

  it("never leaks raw bodies: falls back to a generic message", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status: 500, json: async () => { throw new Error("nope"); } }),
    );
    const { get } = await import("../api/client");
    await expect(get("/x")).rejects.toMatchObject({ status: 500, message: "Request failed (500)" });
    vi.unstubAllGlobals();
  });

  it("builds query strings skipping empty params", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ data: [] }) });
    vi.stubGlobal("fetch", fetchMock);
    const { get } = await import("../api/client");
    await get("/recommendations", { page: 2, ticker: "NVDA", show: null, analyst: "" });
    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain("page=2");
    expect(url).toContain("ticker=NVDA");
    expect(url).not.toContain("show");
    expect(url).not.toContain("analyst");
    vi.unstubAllGlobals();
  });
});
