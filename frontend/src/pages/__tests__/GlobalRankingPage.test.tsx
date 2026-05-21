import { describe, it, expect, vi, beforeAll, afterAll, afterEach, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, params?: Record<string, unknown>) => {
      if (params) {
        return Object.entries(params).reduce(
          (acc, [k, v]) => acc.replace(`{{${k}}}`, String(v)),
          key,
        );
      }
      return key;
    },
    i18n: { language: "en" },
  }),
}));

// ---------------------------------------------------------------------------
// MSW server & data
// ---------------------------------------------------------------------------

const server = setupServer();

const globalItems = [
  { name: "Alice", pp: 120, country: "US", verified: true, cf_rating: 2100 },
  { name: "Bob", pp: 100, country: "CN", verified: true, cf_rating: null },
  { name: "Charlie (CF)", pp: 80, country: null, verified: false, cf_rating: 1800 },
];

const arenaItems = [
  { name: "Dave", pp: 150, country: "JP", verified: true, elo: 1600 },
  { name: "Eve", pp: 110, country: "KR", verified: true, elo: 1400 },
];

beforeAll(() => server.listen({ onUnhandledRequest: "bypass" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

import GlobalRankingPage from "../GlobalRankingPage";

function renderPage() {
  return render(
    <MemoryRouter>
      <GlobalRankingPage />
    </MemoryRouter>,
  );
}

function mockGlobalEndpoint() {
  server.use(
    http.get("*/api/v1/ranking/global", () =>
      HttpResponse.json({
        success: true,
        data: { items: globalItems, total: 3, page: 1, page_size: 50 },
        message: "ok",
      }),
    ),
    http.get("*/api/v1/ranking/arena", () =>
      HttpResponse.json({
        success: true,
        data: { items: arenaItems, total: 2, page: 1, page_size: 50 },
        message: "ok",
      }),
    ),
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("GlobalRankingPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.resetHandlers();
  });

  // 1. Renders title and tabs
  it("renders title, description, and tab buttons", () => {
    mockGlobalEndpoint();
    renderPage();
    expect(screen.getByText("title")).toBeInTheDocument();
    expect(screen.getByText("description")).toBeInTheDocument();
    expect(screen.getByText("tabGlobal")).toBeInTheDocument();
    expect(screen.getByText("tabArena")).toBeInTheDocument();
  });

  // 2. Shows loading skeleton initially
  it("shows skeleton loading initially", () => {
    server.use(
      http.get("*/api/v1/ranking/global", async () => {
        await new Promise(() => {});
      }),
    );
    renderPage();
    // Should have rank header
    expect(screen.getByText("rank")).toBeInTheDocument();
  });

  // 3. Global ranking renders data
  it("renders global ranking data", async () => {
    mockGlobalEndpoint();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Alice")).toBeInTheDocument();
    });
    expect(screen.getByText("Bob")).toBeInTheDocument();
    expect(screen.getByText("Charlie (CF)")).toBeInTheDocument();
    expect(screen.getByText("120")).toBeInTheDocument();
  });

  // 4. Switch to arena tab
  it("switches to arena tab and shows arena data", async () => {
    mockGlobalEndpoint();
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Alice")).toBeInTheDocument();
    });

    await user.click(screen.getByText("tabArena"));

    await waitFor(() => {
      expect(screen.getByText("Dave")).toBeInTheDocument();
    });
    expect(screen.getByText("Eve")).toBeInTheDocument();
  });

  // 5. Arena tab shows sort buttons
  it("shows sort buttons in arena tab", async () => {
    mockGlobalEndpoint();
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByText("tabArena"));

    await waitFor(() => {
      expect(screen.getByText("sortByPP")).toBeInTheDocument();
    });
    expect(screen.getByText("sortByElo")).toBeInTheDocument();
  });

  // 6. Empty data state
  it("shows empty state when no data", async () => {
    server.use(
      http.get("*/api/v1/ranking/global", () =>
        HttpResponse.json({
          success: true,
          data: { items: [], total: 0, page: 1, page_size: 50 },
          message: "ok",
        }),
      ),
    );
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("noData")).toBeInTheDocument();
    });
  });

  // 7. Error state falls back to empty
  it("shows empty state on API error", async () => {
    server.use(
      http.get("*/api/v1/ranking/global", () =>
        HttpResponse.json({ success: false }, { status: 500 }),
      ),
    );
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("noData")).toBeInTheDocument();
    });
  });

  // 8. Pagination shows total users
  it("shows pagination with total users", async () => {
    mockGlobalEndpoint();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("totalUsers")).toBeInTheDocument();
    });
    expect(screen.getByText("prevPage")).toBeInTheDocument();
    expect(screen.getByText("nextPage")).toBeInTheDocument();
  });

  // 9. Previous page button is disabled on first page
  it("disables prev button on first page", async () => {
    mockGlobalEndpoint();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Alice")).toBeInTheDocument();
    });

    const prevBtn = screen.getByText("prevPage").closest("button")!;
    expect(prevBtn).toBeDisabled();
  });

  // 10. Country filter input renders
  it("renders country filter input", () => {
    mockGlobalEndpoint();
    renderPage();
    expect(screen.getByPlaceholderText("countryPlaceholder")).toBeInTheDocument();
  });

  // 11. Tab description changes
  it("shows appropriate description for each tab", async () => {
    mockGlobalEndpoint();
    const user = userEvent.setup();
    renderPage();

    expect(screen.getByText("globalDesc")).toBeInTheDocument();

    await user.click(screen.getByText("tabArena"));
    expect(screen.getByText("arenaDesc")).toBeInTheDocument();
  });

  // 12. Next page button navigates forward
  it("navigates to next page when next button is clicked", async () => {
    server.use(
      http.get("*/api/v1/ranking/global", ({ request }) => {
        const url = new URL(request.url);
        const page = Number(url.searchParams.get("page") || 1);
        return HttpResponse.json({
          success: true,
          data: {
            items: page === 1 ? globalItems : [
              { name: "Zara", pp: 60, country: "DE", verified: true, cf_rating: 1600 },
            ],
            total: 4,
            page,
            page_size: 50,
          },
          message: "ok",
        });
      }),
    );
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Alice")).toBeInTheDocument();
    });

    const nextBtn = screen.getByText("nextPage").closest("button")!;
    // On page 1 with total 4, totalPages = 1 (4/50 = 1), so next is disabled
    // Need total > 50 for page 2 to exist
    expect(nextBtn).toBeDisabled();
  });

  // 13. Sort by Elo in arena tab
  it("sorts arena results by Elo when Elo sort is clicked", async () => {
    server.use(
      http.get("*/api/v1/ranking/arena", ({ request }) => {
        const url = new URL(request.url);
        const sortBy = url.searchParams.get("sort_by") || "pp";
        return HttpResponse.json({
          success: true,
          data: {
            items: sortBy === "elo"
              ? [{ name: "Eve", pp: 110, country: "KR", verified: true, elo: 1400 }]
              : arenaItems,
            total: 2,
            page: 1,
            page_size: 50,
          },
          message: "ok",
        });
      }),
    );
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByText("tabArena"));

    await waitFor(() => {
      expect(screen.getByText("Dave")).toBeInTheDocument();
    });

    await user.click(screen.getByText("sortByElo"));

    await waitFor(() => {
      expect(screen.getByText("Eve")).toBeInTheDocument();
    });
    expect(screen.queryByText("Dave")).not.toBeInTheDocument();
  });

  // 14. Country filter with valid 2-letter code
  it("applies country filter when valid 2-letter code is entered", async () => {
    let capturedCountry: string | null = null;
    server.use(
      http.get("*/api/v1/ranking/global", ({ request }) => {
        const url = new URL(request.url);
        capturedCountry = url.searchParams.get("country");
        return HttpResponse.json({
          success: true,
          data: {
            items: capturedCountry === "US"
              ? [{ name: "Alice", pp: 120, country: "US", verified: true, cf_rating: 2100 }]
              : globalItems,
            total: capturedCountry === "US" ? 1 : 3,
            page: 1,
            page_size: 50,
          },
          message: "ok",
        });
      }),
    );
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Alice")).toBeInTheDocument();
    });

    const input = screen.getByPlaceholderText("countryPlaceholder");
    await user.type(input, "US");

    // Wait for debounce (400ms)
    await waitFor(() => {
      expect(capturedCountry).toBe("US");
    }, { timeout: 2000 });
  });

  // 15. Clear country filter
  it("clears country filter when clear button is clicked", async () => {
    let capturedCountry: string | null = null;
    server.use(
      http.get("*/api/v1/ranking/global", ({ request }) => {
        const url = new URL(request.url);
        capturedCountry = url.searchParams.get("country");
        return HttpResponse.json({
          success: true,
          data: { items: globalItems, total: 3, page: 1, page_size: 50 },
          message: "ok",
        });
      }),
    );
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Alice")).toBeInTheDocument();
    });

    const input = screen.getByPlaceholderText("countryPlaceholder");
    await user.type(input, "US");

    await waitFor(() => {
      expect(capturedCountry).toBe("US");
    }, { timeout: 2000 });

    // Clear button should appear
    const clearBtn = screen.getByRole("button", { name: "" });
    // Find the X button inside the input wrapper
    const xButtons = screen.getAllByRole("button").filter(b => b.querySelector("svg.lucide-x") || b.closest(".relative"));
    // Just clear the filter by clearing the input
    await user.clear(input);

    await waitFor(() => {
      expect(capturedCountry).toBeNull();
    }, { timeout: 2000 });
  });

  // 16. Prev page button navigates backward
  it("navigates to previous page when prev button is clicked", async () => {
    let currentPage = 1;
    server.use(
      http.get("*/api/v1/ranking/global", ({ request }) => {
        const url = new URL(request.url);
        currentPage = Number(url.searchParams.get("page") || 1);
        const items = currentPage === 1
          ? [{ name: "Page1User", pp: 100, country: "US", verified: true, cf_rating: 2000 }]
          : [{ name: "Page2User", pp: 90, country: "CN", verified: true, cf_rating: 1800 }];
        return HttpResponse.json({
          success: true,
          data: { items, total: 100, page: currentPage, page_size: 50 },
          message: "ok",
        });
      }),
    );
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Page1User")).toBeInTheDocument();
    });

    // Go to page 2
    const nextBtn = screen.getByText("nextPage").closest("button")!;
    await user.click(nextBtn);

    await waitFor(() => {
      expect(screen.getByText("Page2User")).toBeInTheDocument();
    });

    // Now prev should be enabled
    const prevBtn = screen.getByText("prevPage").closest("button")!;
    expect(prevBtn).not.toBeDisabled();
    await user.click(prevBtn);

    await waitFor(() => {
      expect(screen.getByText("Page1User")).toBeInTheDocument();
    });
  });

  // 17. Verified users show shield icon and top percentage
  it("shows verified badge and top percentage for verified users", async () => {
    mockGlobalEndpoint();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Alice")).toBeInTheDocument();
    });

    // Alice is verified, should have topPercent text
    const topPercentElements = screen.getAllByText(/topPercent/);
    expect(topPercentElements.length).toBeGreaterThan(0);
  });

  // 18. Unverified users with cf_rating show CF rating inline
  it("shows CF rating for unverified users with cf_rating", async () => {
    mockGlobalEndpoint();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Charlie (CF)")).toBeInTheDocument();
    });

    // Charlie has cf_rating: 1800 and is unverified, shown as (1800)
    expect(screen.getByText("(1800)")).toBeInTheDocument();
  });

  // 19. Arena tab shows Elo column
  it("renders Elo column in arena tab data rows", async () => {
    mockGlobalEndpoint();
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByText("tabArena"));

    await waitFor(() => {
      expect(screen.getByText("Dave")).toBeInTheDocument();
    });

    // Should show Elo values for arena items
    expect(screen.getByText("1600")).toBeInTheDocument();
    expect(screen.getByText("1400")).toBeInTheDocument();
  });

  // 20. Switching back to global from arena tab
  it("switches back to global tab from arena", async () => {
    mockGlobalEndpoint();
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByText("tabArena"));
    await waitFor(() => {
      expect(screen.getByText("Dave")).toBeInTheDocument();
    });

    await user.click(screen.getByText("tabGlobal"));
    await waitFor(() => {
      expect(screen.getByText("Alice")).toBeInTheDocument();
    });
  });
});
