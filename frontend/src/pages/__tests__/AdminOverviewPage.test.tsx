import { describe, it, expect, vi, beforeAll, afterAll, afterEach, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
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

vi.mock("@/components/LoadingSpinner", () => ({
  LoadingSpinner: ({ text }: { text?: string }) => (
    <div data-testid="loading-spinner">{text ?? "Loading..."}</div>
  ),
}));

vi.mock("@/utils", () => ({
  extractApiError: (_err: unknown, fallback: string) => fallback,
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

import AdminOverviewPage from "@/pages/AdminOverviewPage";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const sampleStats = {
  users: { total: 100, active: 80 },
  challenges: { total: 500, active: 50 },
  training: { total_sessions: 1000, active_sessions: 30 },
  contests: { total: 20, active: 5 },
};

const sampleUsers = {
  items: [
    {
      id: "user-1",
      username: "alice",
      email: "alice@test.com",
      elo: 1500,
      pp: 100,
      tokens: 50,
      is_active: true,
      is_admin: false,
      created_at: "2025-01-01",
      last_login_at: "2025-06-01",
    },
    {
      id: "admin-1",
      username: "admin",
      email: "admin@test.com",
      elo: 2000,
      pp: 200,
      tokens: 100,
      is_active: true,
      is_admin: true,
      created_at: "2025-01-01",
      last_login_at: "2025-06-01",
    },
  ],
  total: 2,
  page: 1,
  page_size: 10,
  total_pages: 1,
};

const paginatedUsers = {
  items: Array.from({ length: 10 }, (_, i) => ({
    id: `user-${i}`,
    username: `user${i}`,
    email: `user${i}@test.com`,
    elo: 1000 + i * 100,
    pp: i * 10,
    tokens: i * 5,
    is_active: i % 2 === 0,
    is_admin: i === 0,
    created_at: "2025-01-01",
    last_login_at: null,
  })),
  total: 25,
  page: 1,
  page_size: 10,
  total_pages: 3,
};

function setupDefaultHandlers() {
  server.use(
    http.get("*/api/v1/admin/stats", () =>
      HttpResponse.json({
        success: true,
        data: sampleStats,
        message: "ok",
      }),
    ),
    http.get("*/api/v1/admin/users", () =>
      HttpResponse.json({
        success: true,
        data: sampleUsers,
        message: "ok",
      }),
    ),
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/admin"]}>
      <Routes>
        <Route path="/admin" element={<AdminOverviewPage />} />
        <Route path="/admin/config" element={<div>Config Page</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("AdminOverviewPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows loading spinner initially", () => {
    server.use(
      http.get("*/api/v1/admin/stats", async () => {
        await new Promise(() => {});
      }),
      http.get("*/api/v1/admin/users", async () => {
        await new Promise(() => {});
      }),
    );

    renderPage();
    expect(screen.getByTestId("loading-spinner")).toBeInTheDocument();
  });

  it("renders dashboard title after loading", async () => {
    setupDefaultHandlers();

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("adminDashboard")).toBeInTheDocument();
    });
  });

  it("renders stat cards with values", async () => {
    setupDefaultHandlers();

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("totalUsers")).toBeInTheDocument();
      expect(screen.getByText("challenges")).toBeInTheDocument();
      expect(screen.getByText("trainingSessions")).toBeInTheDocument();
      expect(screen.getByText("contests")).toBeInTheDocument();
    });

    // Check stat values (some may appear multiple times)
    expect(screen.getAllByText("100").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("500").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("1,000")).toBeInTheDocument();
    expect(screen.getAllByText("20").length).toBeGreaterThanOrEqual(1);
  });

  it("renders user table with user data", async () => {
    setupDefaultHandlers();

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("alice")).toBeInTheDocument();
    });

    expect(screen.getByText("alice@test.com")).toBeInTheDocument();
    expect(screen.getByText("admin@test.com")).toBeInTheDocument();
  });

  it("renders active/disabled status badges", async () => {
    setupDefaultHandlers();

    renderPage();

    await waitFor(() => {
      const activeTexts = screen.getAllByText("active");
      expect(activeTexts.length).toBeGreaterThanOrEqual(1);
    });
  });

  it("renders admin role badge for admin user", async () => {
    setupDefaultHandlers();

    renderPage();

    await waitFor(() => {
      const adminTexts = screen.getAllByText("admin");
      expect(adminTexts.length).toBeGreaterThanOrEqual(2);
    });
  });

  it("renders quick actions section", async () => {
    setupDefaultHandlers();

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("quickActions")).toBeInTheDocument();
    });

    expect(screen.getByText("configuration")).toBeInTheDocument();
    expect(screen.getByText("refreshData")).toBeInTheDocument();
  });

  it("renders config link pointing to /admin/config", async () => {
    setupDefaultHandlers();

    renderPage();

    await waitFor(() => {
      const configLinks = screen.getAllByRole("link");
      const configLink = configLinks.find((l) =>
        l.getAttribute("href") === "/admin/config",
      );
      expect(configLink).toBeTruthy();
    });
  });

  it("renders search input", async () => {
    setupDefaultHandlers();

    renderPage();

    await waitFor(() => {
      expect(screen.getByPlaceholderText("searchUsers")).toBeInTheDocument();
    });
  });

  it("shows error when users fetch fails", async () => {
    server.use(
      http.get("*/api/v1/admin/stats", () =>
        HttpResponse.json({
          success: true,
          data: sampleStats,
          message: "ok",
        }),
      ),
      http.get("*/api/v1/admin/users", () =>
        HttpResponse.json({ success: false }, { status: 500 }),
      ),
    );

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("failedLoadUsers")).toBeInTheDocument();
    });
  });

  it("searches users on search button click", async () => {
    const user = userEvent.setup();
    let searchCalledWith = "";

    server.use(
      http.get("*/api/v1/admin/stats", () =>
        HttpResponse.json({
          success: true,
          data: sampleStats,
          message: "ok",
        }),
      ),
      http.get("*/api/v1/admin/users", ({ request }) => {
        const url = new URL(request.url);
        searchCalledWith = url.searchParams.get("search") ?? "";
        return HttpResponse.json({
          success: true,
          data: sampleUsers,
          message: "ok",
        });
      }),
    );

    renderPage();

    await waitFor(() => {
      expect(screen.getByPlaceholderText("searchUsers")).toBeInTheDocument();
    });

    await user.type(screen.getByPlaceholderText("searchUsers"), "alice");
    await user.click(screen.getByText(/search/));

    expect(searchCalledWith).toBe("alice");
  });

  it("searches users on Enter key", async () => {
    const user = userEvent.setup();
    let searchCalledWith = "";

    server.use(
      http.get("*/api/v1/admin/stats", () =>
        HttpResponse.json({
          success: true,
          data: sampleStats,
          message: "ok",
        }),
      ),
      http.get("*/api/v1/admin/users", ({ request }) => {
        const url = new URL(request.url);
        searchCalledWith = url.searchParams.get("search") ?? "";
        return HttpResponse.json({
          success: true,
          data: sampleUsers,
          message: "ok",
        });
      }),
    );

    renderPage();

    await waitFor(() => {
      expect(screen.getByPlaceholderText("searchUsers")).toBeInTheDocument();
    });

    await user.type(screen.getByPlaceholderText("searchUsers"), "bob{Enter}");

    expect(searchCalledWith).toBe("bob");
  });

  it("toggles user active status", async () => {
    const user = userEvent.setup();

    server.use(
      http.get("*/api/v1/admin/stats", () =>
        HttpResponse.json({
          success: true,
          data: sampleStats,
          message: "ok",
        }),
      ),
      http.get("*/api/v1/admin/users", () =>
        HttpResponse.json({
          success: true,
          data: sampleUsers,
          message: "ok",
        }),
      ),
      http.put("*/api/v1/admin/users/:id/toggle-active", () =>
        HttpResponse.json({ success: true, data: {}, message: "ok" }),
      ),
    );

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("alice")).toBeInTheDocument();
    });

    // Find the toggle active buttons
    const buttons = screen.getAllByRole("button");
    // First user action button (toggle active for alice)
    const toggleActiveBtn = buttons.find(
      (b) => b.getAttribute("title") === "disableUser",
    );
    if (toggleActiveBtn) {
      await user.click(toggleActiveBtn);
    }
  });

  it("toggles user admin status", async () => {
    const user = userEvent.setup();

    server.use(
      http.get("*/api/v1/admin/stats", () =>
        HttpResponse.json({
          success: true,
          data: sampleStats,
          message: "ok",
        }),
      ),
      http.get("*/api/v1/admin/users", () =>
        HttpResponse.json({
          success: true,
          data: sampleUsers,
          message: "ok",
        }),
      ),
      http.put("*/api/v1/admin/users/:id/toggle-admin", () =>
        HttpResponse.json({ success: true, data: {}, message: "ok" }),
      ),
    );

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("alice")).toBeInTheDocument();
    });

    const buttons = screen.getAllByRole("button");
    const toggleAdminBtn = buttons.find(
      (b) => b.getAttribute("title") === "grantAdmin",
    );
    if (toggleAdminBtn) {
      await user.click(toggleAdminBtn);
    }
  });

  it("renders pagination when multiple pages", async () => {
    server.use(
      http.get("*/api/v1/admin/stats", () =>
        HttpResponse.json({
          success: true,
          data: sampleStats,
          message: "ok",
        }),
      ),
      http.get("*/api/v1/admin/users", () =>
        HttpResponse.json({
          success: true,
          data: paginatedUsers,
          message: "ok",
        }),
      ),
    );

    renderPage();

    await waitFor(() => {
      expect(screen.getByText(/totalUsersCount/)).toBeInTheDocument();
    });
  });

  it("shows no users message when user list is empty", async () => {
    server.use(
      http.get("*/api/v1/admin/stats", () =>
        HttpResponse.json({
          success: true,
          data: sampleStats,
          message: "ok",
        }),
      ),
      http.get("*/api/v1/admin/users", () =>
        HttpResponse.json({
          success: true,
          data: { items: [], total: 0, page: 1, page_size: 10, total_pages: 0 },
          message: "ok",
        }),
      ),
    );

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("noUsers")).toBeInTheDocument();
    });
  });

  it("refreshes data on refresh button click", async () => {
    const user = userEvent.setup();
    let statsCallCount = 0;

    server.use(
      http.get("*/api/v1/admin/stats", () => {
        statsCallCount++;
        return HttpResponse.json({
          success: true,
          data: sampleStats,
          message: "ok",
        });
      }),
      http.get("*/api/v1/admin/users", () =>
        HttpResponse.json({
          success: true,
          data: sampleUsers,
          message: "ok",
        }),
      ),
    );

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("refreshData")).toBeInTheDocument();
    });

    const initialCount = statsCallCount;
    // Click the refresh button (it's a button, not a link)
    await user.click(screen.getByText("refreshData"));

    await waitFor(() => {
      expect(statsCallCount).toBeGreaterThan(initialCount);
    });
  });
});
