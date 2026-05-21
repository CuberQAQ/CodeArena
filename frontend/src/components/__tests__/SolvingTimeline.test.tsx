import { describe, it, expect, vi, beforeAll, afterAll, afterEach, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

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
afterEach(() => server.resetHandlers());
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

  it("renders timeline with prediction data", async () => {
    server.use(
      http.get("*/api/v1/time-factor-prediction", () =>
        HttpResponse.json({
          success: true,
          data: makePredictionData(),
          message: "ok",
        }),
      ),
    );

    render(<SolvingTimeline {...defaultProps} />);

    await waitFor(() => {
      expect(screen.getByText("5m")).toBeInTheDocument();
    });

    expect(screen.getByText("15m")).toBeInTheDocument();
    expect(screen.getByText("30m")).toBeInTheDocument();
    expect(screen.getByText("60m")).toBeInTheDocument();
    expect(screen.getByText("timeline.expected")).toBeInTheDocument();
    expect(screen.getByText(/timeline.expectedTime/)).toBeInTheDocument();
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
});
