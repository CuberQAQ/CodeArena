import { describe, it, expect, vi, beforeAll, afterAll, afterEach, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { _resetPendingCache } from "@/hooks/useTimeFactorPrediction";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      if (opts) return `${key}:${JSON.stringify(opts)}`;
      return key;
    },
    i18n: { language: "en" },
  }),
}));

// ---------------------------------------------------------------------------
// MSW server
// ---------------------------------------------------------------------------

const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "bypass" }));
afterEach(() => {
  server.resetHandlers();
  // Clear the in-flight dedup cache so a hanging promise from a prior test
  // does not pollute subsequent tests.
  _resetPendingCache();
});
afterAll(() => server.close());

// ---------------------------------------------------------------------------
// Import SUT
// ---------------------------------------------------------------------------

import { SolvingTimeline } from "@/components/SolvingTimeline";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const defaultProps = {
  problemId: "1920A",
  problemRating: 1500,
  userElo: 1400,
  startTime: new Date(),
};

function makePredictionData() {
  return {
    expected_time_minutes: 30,
    time_points: [
      { minutes: 5, time_factor: 1.2, elo_change_estimate: 30 },
      { minutes: 15, time_factor: 1.0, elo_change_estimate: 20 },
      { minutes: 30, time_factor: 0.8, elo_change_estimate: 10 },
      { minutes: 60, time_factor: 0.5, elo_change_estimate: -5 },
    ],
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("SolvingTimeline", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Ensure the dedup cache is clean before each test
    _resetPendingCache();
  });

  it("shows loading state initially", () => {
    server.use(
      http.get("*/api/v1/time-factor-prediction", async () => {
        await new Promise(() => {});
      }),
    );

    render(<SolvingTimeline {...defaultProps} />);

    expect(screen.getByText("timeline.title")).toBeInTheDocument();
    expect(document.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
  });

  it("renders SVG chart with prediction data", async () => {
    server.use(
      http.get("*/api/v1/time-factor-prediction", () =>
        HttpResponse.json({
          success: true,
          data: makePredictionData(),
          message: "ok",
        }),
      ),
    );

    const { container } = render(<SolvingTimeline {...defaultProps} />);

    await waitFor(() => {
      // Should render the chart SVG element
      const svg = container.querySelector('svg[data-testid="elo-chart"]');
      expect(svg).toBeInTheDocument();
    });

    // Should have the title
    expect(screen.getByText("timeline.title")).toBeInTheDocument();

    // Should have the expected time footer
    expect(screen.getByText(/timeline.expectedTime/)).toBeInTheDocument();

    const chartSvg = container.querySelector('svg[data-testid="elo-chart"]')!;

    // Should contain area fill paths (positive and negative regions)
    const paths = chartSvg.querySelectorAll("path");
    expect(paths.length).toBeGreaterThanOrEqual(2); // at least positive + negative area paths

    // Should have data point circles
    const circles = chartSvg.querySelectorAll("circle");
    expect(circles.length).toBe(4); // 4 data points

    // Should have a diamond marker (polygon) for expected time
    const diamond = chartSvg.querySelector("polygon");
    expect(diamond).toBeInTheDocument();
  });

  it("colors positive regions green and negative regions red", async () => {
    server.use(
      http.get("*/api/v1/time-factor-prediction", () =>
        HttpResponse.json({
          success: true,
          data: makePredictionData(),
          message: "ok",
        }),
      ),
    );

    const { container } = render(<SolvingTimeline {...defaultProps} />);

    await waitFor(() => {
      expect(container.querySelector('svg[data-testid="elo-chart"]')).toBeInTheDocument();
    });

    const chartSvg = container.querySelector('svg[data-testid="elo-chart"]')!;

    // Area fills should include green (positive) and red (negative) regions
    const areaPaths = chartSvg.querySelectorAll("path[fill]");
    const fills = Array.from(areaPaths).map((p) => p.getAttribute("fill"));
    const hasGreenFill = fills.some((f) => f && f.includes("34,197,94"));
    const hasRedFill = fills.some((f) => f && f.includes("239,68,68"));
    expect(hasGreenFill).toBe(true);
    expect(hasRedFill).toBe(true);
  });

  it("returns null on API error", async () => {
    server.use(
      http.get("*/api/v1/time-factor-prediction", () =>
        HttpResponse.json({ success: false }, { status: 500 }),
      ),
    );

    const { container } = render(<SolvingTimeline {...defaultProps} />);

    await waitFor(() => {
      expect(container.innerHTML).toBe("");
    });
  });

  it("returns null when data has no time points", async () => {
    server.use(
      http.get("*/api/v1/time-factor-prediction", () =>
        HttpResponse.json({
          success: true,
          data: { expected_time_minutes: 0, time_points: [] },
          message: "ok",
        }),
      ),
    );

    const { container } = render(<SolvingTimeline {...defaultProps} />);

    await waitFor(() => {
      expect(container.innerHTML).toBe("");
    });
  });

  it("returns null when data has only one time point", async () => {
    server.use(
      http.get("*/api/v1/time-factor-prediction", () =>
        HttpResponse.json({
          success: true,
          data: {
            expected_time_minutes: 5,
            time_points: [{ minutes: 5, time_factor: 1.0, elo_change_estimate: 10 }],
          },
          message: "ok",
        }),
      ),
    );

    const { container } = render(<SolvingTimeline {...defaultProps} />);

    await waitFor(() => {
      expect(container.innerHTML).toBe("");
    });
  });

  it("renders all-positive data without negative regions", async () => {
    server.use(
      http.get("*/api/v1/time-factor-prediction", () =>
        HttpResponse.json({
          success: true,
          data: {
            expected_time_minutes: 15,
            time_points: [
              { minutes: 5, time_factor: 1.2, elo_change_estimate: 30 },
              { minutes: 15, time_factor: 1.0, elo_change_estimate: 20 },
              { minutes: 30, time_factor: 0.8, elo_change_estimate: 10 },
            ],
          },
          message: "ok",
        }),
      ),
    );

    const { container } = render(<SolvingTimeline {...defaultProps} />);

    await waitFor(() => {
      expect(container.querySelector('svg[data-testid="elo-chart"]')).toBeInTheDocument();
    });

    const chartSvg = container.querySelector('svg[data-testid="elo-chart"]')!;

    // Should have area paths but only positive (green) fills
    const areaPaths = chartSvg.querySelectorAll("path[fill]");
    const fills = Array.from(areaPaths).map((p) => p.getAttribute("fill"));
    const hasRedFill = fills.some((f) => f && f.includes("239,68,68"));
    expect(hasRedFill).toBe(false);
  });

  it("renders all-negative data without positive regions", async () => {
    server.use(
      http.get("*/api/v1/time-factor-prediction", () =>
        HttpResponse.json({
          success: true,
          data: {
            expected_time_minutes: 15,
            time_points: [
              { minutes: 5, time_factor: 0.5, elo_change_estimate: -5 },
              { minutes: 15, time_factor: 0.3, elo_change_estimate: -10 },
              { minutes: 30, time_factor: 0.1, elo_change_estimate: -20 },
            ],
          },
          message: "ok",
        }),
      ),
    );

    const { container } = render(<SolvingTimeline {...defaultProps} />);

    await waitFor(() => {
      expect(container.querySelector('svg[data-testid="elo-chart"]')).toBeInTheDocument();
    });

    const chartSvg = container.querySelector('svg[data-testid="elo-chart"]')!;

    // Should have area paths but only negative (red) fills
    const areaPaths = chartSvg.querySelectorAll("path[fill]");
    const fills = Array.from(areaPaths).map((p) => p.getAttribute("fill"));
    const hasGreenFill = fills.some((f) => f && f.includes("34,197,94"));
    expect(hasGreenFill).toBe(false);
  });

  it("renders the zero line as a horizontal dashed line", async () => {
    server.use(
      http.get("*/api/v1/time-factor-prediction", () =>
        HttpResponse.json({
          success: true,
          data: makePredictionData(),
          message: "ok",
        }),
      ),
    );

    const { container } = render(<SolvingTimeline {...defaultProps} />);

    await waitFor(() => {
      expect(container.querySelector('svg[data-testid="elo-chart"]')).toBeInTheDocument();
    });

    const chartSvg = container.querySelector('svg[data-testid="elo-chart"]')!;

    // Find horizontal dashed lines (zero line uses strokeDasharray="3,3")
    const dashedLines = Array.from(chartSvg.querySelectorAll("line")).filter(
      (el) => el.getAttribute("stroke-dasharray") === "3,3",
    );

    // At least one horizontal dashed line exists (the zero line)
    expect(dashedLines.length).toBeGreaterThanOrEqual(1);

    // The zero line should span the full chart width
    const zeroLine = dashedLines[0];
    const y1 = parseFloat(zeroLine.getAttribute("y1")!);
    const y2 = parseFloat(zeroLine.getAttribute("y2")!);
    expect(y1).toBe(y2); // horizontal line: y1 === y2
    expect(parseFloat(zeroLine.getAttribute("x1")!)).toBeLessThan(
      parseFloat(zeroLine.getAttribute("x2")!),
    );
  });

  it("renders current time vertical line when within chart range", async () => {
    // Set startTime to 20 minutes ago so currentMinutes=20 falls within 5..60 range
    const startTime = new Date(Date.now() - 20 * 60_000);

    server.use(
      http.get("*/api/v1/time-factor-prediction", () =>
        HttpResponse.json({
          success: true,
          data: makePredictionData(),
          message: "ok",
        }),
      ),
    );

    const { container } = render(<SolvingTimeline {...defaultProps} startTime={startTime} />);

    await waitFor(() => {
      expect(container.querySelector('svg[data-testid="elo-chart"]')).toBeInTheDocument();
    });

    const chartSvg = container.querySelector('svg[data-testid="elo-chart"]')!;

    // Current time vertical line: a solid line spanning from PADDING_TOP to VB_HEIGHT-PADDING_BOTTOM
    // It has strokeWidth="1" and strokeOpacity="0.5" (the zero line has strokeOpacity="0.2")
    const solidLines = Array.from(chartSvg.querySelectorAll("line")).filter(
      (el) => {
        const opacity = el.getAttribute("stroke-opacity");
        const dashArray = el.getAttribute("stroke-dasharray");
        // Current time line: opacity=0.6, no dash array
        return opacity === "0.6" && !dashArray;
      },
    );

    expect(solidLines.length).toBeGreaterThanOrEqual(1);

    // It should be vertical: x1 === x2
    const currentLine = solidLines[0];
    expect(currentLine.getAttribute("x1")).toBe(currentLine.getAttribute("x2"));

    // x should be between PADDING_LEFT and VB_WIDTH - PADDING_RIGHT
    const x = parseFloat(currentLine.getAttribute("x1")!);
    expect(x).toBeGreaterThan(4); // PADDING_LEFT=4
    expect(x).toBeLessThan(216); // VB_WIDTH - PADDING_RIGHT = 220-4=216
  });

  it("renders expected time diamond marker", async () => {
    server.use(
      http.get("*/api/v1/time-factor-prediction", () =>
        HttpResponse.json({
          success: true,
          data: makePredictionData(),
          message: "ok",
        }),
      ),
    );

    const { container } = render(<SolvingTimeline {...defaultProps} />);

    await waitFor(() => {
      expect(container.querySelector('svg[data-testid="elo-chart"]')).toBeInTheDocument();
    });

    const chartSvg = container.querySelector('svg[data-testid="elo-chart"]')!;

    // Diamond marker is a <polygon> with points "0,-4 4,0 0,4 -4,0"
    const diamond = chartSvg.querySelector("polygon");
    expect(diamond).toBeInTheDocument();
    expect(diamond!.getAttribute("points")).toBe("0,-4 4,0 0,4 -4,0");

    // Diamond should be inside a <g> with a transform (translate to expected point)
    const g = diamond!.closest("g");
    expect(g).toBeInTheDocument();
    const transform = g!.getAttribute("transform");
    expect(transform).toMatch(/^translate\(/);
  });

  it("uses aria-label on SVG for accessibility", async () => {
    server.use(
      http.get("*/api/v1/time-factor-prediction", () =>
        HttpResponse.json({
          success: true,
          data: makePredictionData(),
          message: "ok",
        }),
      ),
    );

    const { container } = render(<SolvingTimeline {...defaultProps} />);

    await waitFor(() => {
      const svg = container.querySelector('svg[data-testid="elo-chart"]');
      expect(svg).toBeInTheDocument();
    });

    const svg = container.querySelector('svg[data-testid="elo-chart"]')!;
    expect(svg.getAttribute("role")).toBe("img");
    expect(svg.getAttribute("aria-label")).toBe("timeline.title");
  });

  it("renders SVG with textRendering=geometricPrecision", async () => {
    server.use(
      http.get("*/api/v1/time-factor-prediction", () =>
        HttpResponse.json({
          success: true,
          data: makePredictionData(),
          message: "ok",
        }),
      ),
    );

    const { container } = render(<SolvingTimeline {...defaultProps} />);

    await waitFor(() => {
      expect(container.querySelector('svg[data-testid="elo-chart"]')).toBeInTheDocument();
    });

    const svg = container.querySelector('svg[data-testid="elo-chart"]')!;
    // React renders textRendering as "text-rendering" attribute in DOM
    expect(svg.getAttribute("text-rendering")).toBe("geometricPrecision");
  });

  it("uses system-ui fontFamily on all text elements", async () => {
    server.use(
      http.get("*/api/v1/time-factor-prediction", () =>
        HttpResponse.json({
          success: true,
          data: makePredictionData(),
          message: "ok",
        }),
      ),
    );

    const { container } = render(<SolvingTimeline {...defaultProps} />);

    await waitFor(() => {
      expect(container.querySelector('svg[data-testid="elo-chart"]')).toBeInTheDocument();
    });

    const chartSvg = container.querySelector('svg[data-testid="elo-chart"]')!;
    const textElements = chartSvg.querySelectorAll("text");
    expect(textElements.length).toBeGreaterThan(0);

    for (const text of Array.from(textElements)) {
      expect(text.getAttribute("font-family")).toBe("system-ui, sans-serif");
    }
  });

  it("renders a transparent hover hit area with crosshair cursor", async () => {
    server.use(
      http.get("*/api/v1/time-factor-prediction", () =>
        HttpResponse.json({
          success: true,
          data: makePredictionData(),
          message: "ok",
        }),
      ),
    );

    const { container } = render(<SolvingTimeline {...defaultProps} />);

    await waitFor(() => {
      expect(container.querySelector('svg[data-testid="elo-chart"]')).toBeInTheDocument();
    });

    const chartSvg = container.querySelector('svg[data-testid="elo-chart"]')!;

    // Find the hover hit area rect: transparent fill with crosshair cursor
    const rects = chartSvg.querySelectorAll("rect");
    const hitArea = Array.from(rects).find(
      (r) => r.getAttribute("fill") === "transparent" && r.getAttribute("cursor") === "crosshair",
    );
    expect(hitArea).toBeInTheDocument();

    // Should cover the full chart area
    expect(hitArea!.getAttribute("x")).toBe("22"); // PADDING_LEFT
    expect(hitArea!.getAttribute("y")).toBe("8");  // PADDING_TOP
    expect(hitArea!.getAttribute("width")).toBe("194"); // CHART_WIDTH = 220-22-4
    expect(hitArea!.getAttribute("height")).toBe("74"); // CHART_HEIGHT = 100-8-18
  });

  it("shows tooltip on mouse move within chart area", async () => {
    server.use(
      http.get("*/api/v1/time-factor-prediction", () =>
        HttpResponse.json({
          success: true,
          data: makePredictionData(),
          message: "ok",
        }),
      ),
    );

    const { container } = render(<SolvingTimeline {...defaultProps} />);

    await waitFor(() => {
      expect(container.querySelector('svg[data-testid="elo-chart"]')).toBeInTheDocument();
    });

    const chartSvg = container.querySelector('svg[data-testid="elo-chart"]')!;

    // Find the hover hit area
    const rects = chartSvg.querySelectorAll("rect");
    const hitArea = Array.from(rects).find(
      (r) => r.getAttribute("fill") === "transparent" && r.getAttribute("cursor") === "crosshair",
    )!;
    expect(hitArea).toBeTruthy();

    // Mock SVG coordinate transform APIs for jsdom
    // The handler uses createSVGPoint + getScreenCTM to convert client coords to SVG coords
    const mockSvgPoint = {
      x: 0,
      y: 0,
      matrixTransform: vi.fn().mockReturnValue({ x: 80, y: 50 }), // SVG coord within chart
    };
    const mockCtm = { a: 1, b: 0, c: 0, d: 1, e: 0, f: 0 };

    const svgElement = hitArea.closest("svg")!;
    svgElement.createSVGPoint = vi.fn().mockReturnValue(mockSvgPoint);
    svgElement.getScreenCTM = vi.fn().mockReturnValue({
      ...mockCtm,
      inverse: vi.fn().mockReturnValue(mockCtm),
    });

    // Fire mouse move event using fireEvent to trigger React's synthetic event system
    fireEvent.mouseMove(hitArea, { clientX: 300, clientY: 200 });

    // After mouse move, tooltip elements should appear
    // The tooltip renders a vertical dashed line, a dot (circle r=3), and a text label
    await waitFor(() => {
      // Look for the hover dot (r=3, which is larger than data point dots at r=1.5 or r=2.5)
      const circles = chartSvg.querySelectorAll("circle");
      const hoverDot = Array.from(circles).find((c) => c.getAttribute("r") === "3");
      expect(hoverDot).toBeInTheDocument();
    });

    // Should have tooltip text with format "{minutes}m | {elo}"
    const tooltipTexts = Array.from(chartSvg.querySelectorAll("text")).filter(
      (t) => t.textContent?.includes("m |"),
    );
    expect(tooltipTexts.length).toBeGreaterThan(0);

    // Should have a popover-styled rect for the tooltip background
    const tooltipRect = Array.from(chartSvg.querySelectorAll("rect")).find(
      (r) => r.getAttribute("fill")?.includes("popover"),
    );
    expect(tooltipRect).toBeInTheDocument();
  });

  it("hides tooltip on mouse leave", async () => {
    server.use(
      http.get("*/api/v1/time-factor-prediction", () =>
        HttpResponse.json({
          success: true,
          data: makePredictionData(),
          message: "ok",
        }),
      ),
    );

    const { container } = render(<SolvingTimeline {...defaultProps} />);

    await waitFor(() => {
      expect(container.querySelector('svg[data-testid="elo-chart"]')).toBeInTheDocument();
    });

    const chartSvg = container.querySelector('svg[data-testid="elo-chart"]')!;
    const rects = chartSvg.querySelectorAll("rect");
    const hitArea = Array.from(rects).find(
      (r) => r.getAttribute("fill") === "transparent" && r.getAttribute("cursor") === "crosshair",
    )!;

    // Mock SVG coordinate transform APIs
    const mockSvgPoint = {
      x: 0,
      y: 0,
      matrixTransform: vi.fn().mockReturnValue({ x: 80, y: 50 }),
    };
    const mockCtm = { a: 1, b: 0, c: 0, d: 1, e: 0, f: 0 };
    const svgElement = hitArea.closest("svg")!;
    svgElement.createSVGPoint = vi.fn().mockReturnValue(mockSvgPoint);
    svgElement.getScreenCTM = vi.fn().mockReturnValue({
      ...mockCtm,
      inverse: vi.fn().mockReturnValue(mockCtm),
    });

    // First show tooltip
    fireEvent.mouseMove(hitArea, { clientX: 300, clientY: 200 });

    await waitFor(() => {
      const circles = chartSvg.querySelectorAll("circle");
      const hoverDot = Array.from(circles).find((c) => c.getAttribute("r") === "3");
      expect(hoverDot).toBeInTheDocument();
    });

    // Now mouse leave
    fireEvent.mouseLeave(hitArea);

    // Tooltip should be gone: no r=3 circle should exist
    await waitFor(() => {
      const circles = chartSvg.querySelectorAll("circle");
      const hoverDots = Array.from(circles).filter((c) => c.getAttribute("r") === "3");
      expect(hoverDots).toHaveLength(0);
    });
  });
});
