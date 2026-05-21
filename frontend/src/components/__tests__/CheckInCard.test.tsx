import { describe, it, expect, vi, beforeAll, afterAll, afterEach, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

import { CheckInCard } from "@/components/CheckInCard";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeCheckedInStatus(overrides = {}) {
  return {
    checked_in_today: true,
    streak_days: 5,
    next_reward: 10,
    can_makeup: false,
    makeup_used_this_week: 0,
    makeup_limit: 3,
    checked_dates_this_week: [
      new Date().toISOString().split("T")[0],
    ],
    ...overrides,
  };
}

function makeNotCheckedInStatus(overrides = {}) {
  return {
    checked_in_today: false,
    streak_days: 2,
    next_reward: 5,
    can_makeup: true,
    makeup_used_this_week: 1,
    makeup_limit: 3,
    checked_dates_this_week: [],
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("CheckInCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows loading state initially", () => {
    server.use(
      http.get("*/api/v1/checkin/status", async () => {
        await new Promise(() => {});
      }),
    );

    render(<CheckInCard />);
    expect(document.querySelector(".animate-pulse")).toBeInTheDocument();
  });

  it("shows checked-in state when already checked in today", async () => {
    server.use(
      http.get("*/api/v1/checkin/status", () =>
        HttpResponse.json({
          success: true,
          data: makeCheckedInStatus(),
          message: "ok",
        }),
      ),
    );

    render(<CheckInCard />);

    await waitFor(() => {
      expect(screen.getByText("checkin.checkedIn")).toBeInTheDocument();
    });
  });

  it("shows check-in button when not checked in today", async () => {
    server.use(
      http.get("*/api/v1/checkin/status", () =>
        HttpResponse.json({
          success: true,
          data: makeNotCheckedInStatus(),
          message: "ok",
        }),
      ),
    );

    render(<CheckInCard />);

    await waitFor(() => {
      expect(screen.getByText("checkin.checkin")).toBeInTheDocument();
    });
  });

  it("shows makeup button when can_makeup is true", async () => {
    server.use(
      http.get("*/api/v1/checkin/status", () =>
        HttpResponse.json({
          success: true,
          data: makeNotCheckedInStatus({ can_makeup: true }),
          message: "ok",
        }),
      ),
    );

    render(<CheckInCard />);

    await waitFor(() => {
      expect(screen.getByText("checkin.makeup")).toBeInTheDocument();
    });
  });

  it("shows streak badge when streak_days > 0", async () => {
    server.use(
      http.get("*/api/v1/checkin/status", () =>
        HttpResponse.json({
          success: true,
          data: makeCheckedInStatus({ streak_days: 5 }),
          message: "ok",
        }),
      ),
    );

    render(<CheckInCard />);

    await waitFor(() => {
      expect(screen.getByText(/checkin.streakShort/)).toBeInTheDocument();
    });
  });

  it("returns null when status fetch fails with no data", async () => {
    server.use(
      http.get("*/api/v1/checkin/status", () =>
        HttpResponse.json({ success: false }, { status: 500 }),
      ),
    );

    const { container } = render(<CheckInCard />);

    await waitFor(() => {
      expect(container.innerHTML).toBe("");
    });
  });

  it("performs check-in and refreshes status", async () => {
    const user = userEvent.setup();
    let checkinCalled = false;

    server.use(
      http.get("*/api/v1/checkin/status", () => {
        if (checkinCalled) {
          return HttpResponse.json({
            success: true,
            data: makeCheckedInStatus(),
            message: "ok",
          });
        }
        return HttpResponse.json({
          success: true,
          data: makeNotCheckedInStatus(),
          message: "ok",
        });
      }),
      http.post("*/api/v1/checkin", () => {
        checkinCalled = true;
        return HttpResponse.json({
          success: true,
          data: { tokens_earned: 5 },
          message: "ok",
        });
      }),
    );

    render(<CheckInCard />);

    await waitFor(() => {
      expect(screen.getByText("checkin.checkin")).toBeInTheDocument();
    });

    await user.click(screen.getByText("checkin.checkin"));

    await waitFor(() => {
      expect(screen.getByText("checkin.checkedIn")).toBeInTheDocument();
    });
  });
});
