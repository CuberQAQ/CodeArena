import { describe, it, expect, vi, beforeAll, afterAll, afterEach, beforeEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
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

vi.mock("@/utils", () => ({
  getRatingColor: (rating: number) => {
    if (rating >= 2400) return "#FF0000";
    if (rating >= 2100) return "#FF8C00";
    if (rating >= 1900) return "#AA00AA";
    if (rating >= 1600) return "#0000FF";
    if (rating >= 1400) return "#03A89E";
    if (rating >= 1200) return "#008000";
    return "#808080";
  },
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

import { EloProgressBar } from "@/components/EloProgressBar";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makePredictionData(eloChange = 15) {
  return {
    expected_time_minutes: 30,
    time_points: [
      { minutes: 5, time_factor: 1.2, elo_change_estimate: eloChange },
      { minutes: 15, time_factor: 1.0, elo_change_estimate: 10 },
      { minutes: 30, time_factor: 0.8, elo_change_estimate: 5 },
    ],
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("EloProgressBar", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ---- Basic rendering ----

  it("renders M-Elo value with color", () => {
    server.use(
      http.get("*/api/v1/time-factor-prediction", async () => {
        await new Promise(() => {});
      }),
    );

    render(
      <EloProgressBar
        melo={1500}
        currentMedalThreshold={1200}
        nextMedalThreshold={1600}
      />,
    );

    expect(screen.getByText("eloProgress.meloLabel")).toBeInTheDocument();
    expect(screen.getByText("1500")).toBeInTheDocument();
  });

  it("renders progress bar with correct structure", () => {
    server.use(
      http.get("*/api/v1/time-factor-prediction", async () => {
        await new Promise(() => {});
      }),
    );

    const { container } = render(
      <EloProgressBar
        melo={1500}
        currentMedalThreshold={1200}
        nextMedalThreshold={1600}
      />,
    );

    // Should have a progress bar container
    const progressBar = container.querySelector('[class*="rounded-full"]');
    expect(progressBar).toBeTruthy();
  });

  // ---- Medal threshold display ----

  it("shows distance to next medal threshold", () => {
    server.use(
      http.get("*/api/v1/time-factor-prediction", async () => {
        await new Promise(() => {});
      }),
    );

    render(
      <EloProgressBar
        melo={1500}
        currentMedalThreshold={1200}
        nextMedalThreshold={1600}
      />,
    );

    // Distance = 1600 - 1500 = 100
    expect(
      screen.getByText(/eloProgress.untilNext.*100/),
    ).toBeInTheDocument();
  });

  it("shows max tier message when at highest tier (no next threshold)", () => {
    server.use(
      http.get("*/api/v1/time-factor-prediction", async () => {
        await new Promise(() => {});
      }),
    );

    render(
      <EloProgressBar
        melo={2800}
        currentMedalThreshold={2800}
        nextMedalThreshold={null}
      />,
    );

    expect(screen.getByText("eloProgressMax")).toBeInTheDocument();
  });

  it("shows medal labels when next threshold matches a medal", () => {
    server.use(
      http.get("*/api/v1/time-factor-prediction", async () => {
        await new Promise(() => {});
      }),
    );

    render(
      <EloProgressBar
        melo={1300}
        currentMedalThreshold={1200}
        nextMedalThreshold={1400}
      />,
    );

    // 1400 maps to provincial silver
    expect(screen.getByText("medal:types.silver medal:levels.provincial")).toBeInTheDocument();
  });

  // ---- Edge cases: no medal (below 1200) ----

  it("handles no medal state (progress from 0 to first threshold)", () => {
    server.use(
      http.get("*/api/v1/time-factor-prediction", async () => {
        await new Promise(() => {});
      }),
    );

    render(
      <EloProgressBar
        melo={800}
        currentMedalThreshold={null}
        nextMedalThreshold={1200}
      />,
    );

    expect(screen.getByText("800")).toBeInTheDocument();
    // Should show progress from 0 to 1200
    expect(screen.getByText("0")).toBeInTheDocument();
    expect(screen.getByText("1200")).toBeInTheDocument();
  });

  // ---- Prediction overlay ----

  it("shows predicted Elo change from first time point (positive)", async () => {
    server.use(
      http.get("*/api/v1/time-factor-prediction", () =>
        HttpResponse.json({
          success: true,
          data: makePredictionData(15),
          message: "ok",
        }),
      ),
    );

    render(
      <EloProgressBar
        melo={1500}
        currentMedalThreshold={1200}
        nextMedalThreshold={1600}
        problemId="1920A"
        problemRating={1500}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("+15")).toBeInTheDocument();
    });
  });

  it("shows predicted Elo change from first time point (negative)", async () => {
    server.use(
      http.get("*/api/v1/time-factor-prediction", () =>
        HttpResponse.json({
          success: true,
          data: makePredictionData(-8),
          message: "ok",
        }),
      ),
    );

    render(
      <EloProgressBar
        melo={1500}
        currentMedalThreshold={1200}
        nextMedalThreshold={1600}
        problemId="1920A"
        problemRating={1500}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("-8")).toBeInTheDocument();
    });
  });

  it("renders prediction overlay bar (green for gain)", async () => {
    server.use(
      http.get("*/api/v1/time-factor-prediction", () =>
        HttpResponse.json({
          success: true,
          data: makePredictionData(20),
          message: "ok",
        }),
      ),
    );

    const { container } = render(
      <EloProgressBar
        melo={1500}
        currentMedalThreshold={1200}
        nextMedalThreshold={1600}
        problemId="1920A"
        problemRating={1500}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("+20")).toBeInTheDocument();
    });

    // Check green overlay exists (rgb(34, 197, 94) = #22c55e)
    const overlays = container.querySelectorAll('[style*="background-color: rgb(34, 197, 94)"]');
    expect(overlays.length).toBeGreaterThan(0);
  });

  it("renders prediction overlay bar (red for loss)", async () => {
    server.use(
      http.get("*/api/v1/time-factor-prediction", () =>
        HttpResponse.json({
          success: true,
          data: makePredictionData(-10),
          message: "ok",
        }),
      ),
    );

    const { container } = render(
      <EloProgressBar
        melo={1500}
        currentMedalThreshold={1200}
        nextMedalThreshold={1600}
        problemId="1920A"
        problemRating={1500}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("-10")).toBeInTheDocument();
    });

    // Check red overlay exists (rgb(239, 68, 68) = #ef4444)
    const overlays = container.querySelectorAll('[style*="background-color: rgb(239, 68, 68)"]');
    expect(overlays.length).toBeGreaterThan(0);
  });

  // ---- Graceful degradation ----

  it("shows only current position when prediction API fails", async () => {
    server.use(
      http.get("*/api/v1/time-factor-prediction", () =>
        HttpResponse.json({ success: false }, { status: 500 }),
      ),
    );

    render(
      <EloProgressBar
        melo={1500}
        currentMedalThreshold={1200}
        nextMedalThreshold={1600}
        problemId="1920A"
        problemRating={1500}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("1500")).toBeInTheDocument();
    });

    // Should NOT show any predicted change badge
    expect(screen.queryByText(/\+\d+/)).not.toBeInTheDocument();
    expect(screen.queryByText(/-\d+/)).not.toBeInTheDocument();
  });

  it("shows only current position when no prediction data", async () => {
    server.use(
      http.get("*/api/v1/time-factor-prediction", () =>
        HttpResponse.json({
          success: true,
          data: { expected_time_minutes: 0, time_points: [] },
          message: "ok",
        }),
      ),
    );

    render(
      <EloProgressBar
        melo={1500}
        currentMedalThreshold={1200}
        nextMedalThreshold={1600}
        problemId="1920A"
        problemRating={1500}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("1500")).toBeInTheDocument();
    });

    expect(screen.queryByText(/\+\d+/)).not.toBeInTheDocument();
  });

  it("does not fetch prediction when problemId is null", () => {
    const fetchSpy = vi.fn();
    server.use(
      http.get("*/api/v1/time-factor-prediction", () => {
        fetchSpy();
        return HttpResponse.json({ success: true, data: makePredictionData() });
      }),
    );

    render(
      <EloProgressBar
        melo={1500}
        currentMedalThreshold={1200}
        nextMedalThreshold={1600}
        problemId={null}
        problemRating={1500}
      />,
    );

    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("does not fetch prediction when problemRating is null", () => {
    const fetchSpy = vi.fn();
    server.use(
      http.get("*/api/v1/time-factor-prediction", () => {
        fetchSpy();
        return HttpResponse.json({ success: true, data: makePredictionData() });
      }),
    );

    render(
      <EloProgressBar
        melo={1500}
        currentMedalThreshold={1200}
        nextMedalThreshold={1600}
        problemId="1920A"
        problemRating={null}
      />,
    );

    expect(fetchSpy).not.toHaveBeenCalled();
  });

  // ---- Auto-refresh ----

  it("sets up 60-second interval for prediction refresh when problem is set", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });

    let fetchCount = 0;
    server.use(
      http.get("*/api/v1/time-factor-prediction", () => {
        fetchCount++;
        return HttpResponse.json({
          success: true,
          data: makePredictionData(),
        });
      }),
    );

    render(
      <EloProgressBar
        melo={1500}
        currentMedalThreshold={1200}
        nextMedalThreshold={1600}
        problemId="1920A"
        problemRating={1500}
      />,
    );

    // Initial fetch
    await waitFor(() => expect(fetchCount).toBe(1));

    // Advance 60 seconds
    await act(async () => {
      vi.advanceTimersByTime(60_000);
    });
    expect(fetchCount).toBe(2);

    // Advance another 60 seconds
    await act(async () => {
      vi.advanceTimersByTime(60_000);
    });
    expect(fetchCount).toBe(3);

    vi.useRealTimers();
  });

  it("cleans up interval on unmount", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });

    let fetchCount = 0;
    server.use(
      http.get("*/api/v1/time-factor-prediction", () => {
        fetchCount++;
        return HttpResponse.json({
          success: true,
          data: makePredictionData(),
        });
      }),
    );

    const { unmount } = render(
      <EloProgressBar
        melo={1500}
        currentMedalThreshold={1200}
        nextMedalThreshold={1600}
        problemId="1920A"
        problemRating={1500}
      />,
    );

    await waitFor(() => expect(fetchCount).toBe(1));

    unmount();

    // Advance time -- no additional fetches should happen
    await act(async () => {
      vi.advanceTimersByTime(120_000);
    });

    expect(fetchCount).toBe(1); // Still only the initial fetch

    vi.useRealTimers();
  });

  // ---- Rating color mapping ----

  it("uses gray color for low ratings (below 1200)", () => {
    server.use(
      http.get("*/api/v1/time-factor-prediction", async () => {
        await new Promise(() => {});
      }),
    );

    render(
      <EloProgressBar
        melo={1000}
        currentMedalThreshold={null}
        nextMedalThreshold={1200}
      />,
    );

    const eloValue = screen.getByText("1000");
    expect(eloValue).toBeTruthy();
    // Gray color: #808080
    expect(eloValue.style.color).toBe("rgb(128, 128, 128)");
  });

  it("uses green color for Pupil ratings (1200-1399)", () => {
    server.use(
      http.get("*/api/v1/time-factor-prediction", async () => {
        await new Promise(() => {});
      }),
    );

    render(
      <EloProgressBar
        melo={1300}
        currentMedalThreshold={1200}
        nextMedalThreshold={1400}
      />,
    );

    const eloValue = screen.getByText("1300");
    expect(eloValue.style.color).toBe("rgb(0, 128, 0)"); // #008000
  });

  it("uses blue color for Expert ratings (1600-1899)", () => {
    server.use(
      http.get("*/api/v1/time-factor-prediction", async () => {
        await new Promise(() => {});
      }),
    );

    render(
      <EloProgressBar
        melo={1700}
        currentMedalThreshold={1600}
        nextMedalThreshold={1900}
      />,
    );

    const eloValue = screen.getByText("1700");
    expect(eloValue.style.color).toBe("rgb(0, 0, 255)"); // #0000FF
  });

  // ---- Progress bar boundary labels ----

  it("shows boundary labels for current and next thresholds", () => {
    server.use(
      http.get("*/api/v1/time-factor-prediction", async () => {
        await new Promise(() => {});
      }),
    );

    render(
      <EloProgressBar
        melo={1500}
        currentMedalThreshold={1200}
        nextMedalThreshold={1600}
      />,
    );

    expect(screen.getByText("1200")).toBeInTheDocument();
    expect(screen.getByText("1600")).toBeInTheDocument();
  });

  it("shows 0 as lower boundary when no current medal threshold", () => {
    server.use(
      http.get("*/api/v1/time-factor-prediction", async () => {
        await new Promise(() => {});
      }),
    );

    render(
      <EloProgressBar
        melo={800}
        currentMedalThreshold={null}
        nextMedalThreshold={1200}
      />,
    );

    expect(screen.getByText("0")).toBeInTheDocument();
    expect(screen.getByText("1200")).toBeInTheDocument();
  });

  // ---- Progress bar width calculations ----

  it("calculates progress percentage correctly at midpoint", () => {
    server.use(
      http.get("*/api/v1/time-factor-prediction", async () => {
        await new Promise(() => {});
      }),
    );

    const { container } = render(
      <EloProgressBar
        melo={1400}
        currentMedalThreshold={1200}
        nextMedalThreshold={1600}
      />,
    );

    // (1400 - 1200) / (1600 - 1200) = 200/400 = 50%
    const baseBar = container.querySelector('[style*="width: 50%"]');
    expect(baseBar).toBeTruthy();
  });

  it("calculates progress percentage correctly at start", () => {
    server.use(
      http.get("*/api/v1/time-factor-prediction", async () => {
        await new Promise(() => {});
      }),
    );

    const { container } = render(
      <EloProgressBar
        melo={1200}
        currentMedalThreshold={1200}
        nextMedalThreshold={1600}
      />,
    );

    // (1200 - 1200) / (1600 - 1200) = 0%
    const baseBar = container.querySelector('[style*="width: 0%"]');
    expect(baseBar).toBeTruthy();
  });

  it("calculates progress percentage correctly near end", () => {
    server.use(
      http.get("*/api/v1/time-factor-prediction", async () => {
        await new Promise(() => {});
      }),
    );

    const { container } = render(
      <EloProgressBar
        melo={1550}
        currentMedalThreshold={1200}
        nextMedalThreshold={1600}
      />,
    );

    // (1550 - 1200) / (1600 - 1200) = 350/400 = 87.5%
    const baseBar = container.querySelector('[style*="width: 87.5%"]');
    expect(baseBar).toBeTruthy();
  });

  // ---- Trending icons in prediction badge ----

  it("shows trending up icon for positive prediction", async () => {
    server.use(
      http.get("*/api/v1/time-factor-prediction", () =>
        HttpResponse.json({
          success: true,
          data: makePredictionData(12),
          message: "ok",
        }),
      ),
    );

    render(
      <EloProgressBar
        melo={1500}
        currentMedalThreshold={1200}
        nextMedalThreshold={1600}
        problemId="1920A"
        problemRating={1500}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("+12")).toBeInTheDocument();
    });

    // The badge should have green background class
    const badge = screen.getByText("+12").closest("div");
    expect(badge?.className).toContain("bg-green-500/10");
    expect(badge?.className).toContain("text-green-400");
  });

  it("shows trending down icon for negative prediction", async () => {
    server.use(
      http.get("*/api/v1/time-factor-prediction", () =>
        HttpResponse.json({
          success: true,
          data: makePredictionData(-5),
          message: "ok",
        }),
      ),
    );

    render(
      <EloProgressBar
        melo={1500}
        currentMedalThreshold={1200}
        nextMedalThreshold={1600}
        problemId="1920A"
        problemRating={1500}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("-5")).toBeInTheDocument();
    });

    // The badge should have red background class
    const badge = screen.getByText("-5").closest("div");
    expect(badge?.className).toContain("bg-red-500/10");
    expect(badge?.className).toContain("text-red-400");
  });
});
