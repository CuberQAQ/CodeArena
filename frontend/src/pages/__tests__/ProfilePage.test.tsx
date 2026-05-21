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
      if (typeof key === "string" && params) {
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

vi.mock("@/components/LoadingSpinner", () => ({
  LoadingSpinner: ({ text }: { text?: string }) => (
    <div data-testid="loading-spinner">{text ?? "Loading..."}</div>
  ),
}));

vi.mock("@/components/charts/EloChart", () => ({
  EloChart: ({ data }: { data: unknown[] }) => (
    <div data-testid="elo-chart">Chart with {data.length} points</div>
  ),
}));

vi.mock("@/components/medal", () => ({
  MedalBadge: () => <div data-testid="medal-badge" />,
  MedalCabinet: () => <div data-testid="medal-cabinet" />,
  SkillMedalWall: () => <div data-testid="skill-medal-wall" />,
}));

vi.mock("@/components/Avatar", () => ({
  AvatarUpload: () => <div data-testid="avatar-upload" />,
}));

vi.mock("@/components/ProfileCard", () => ({
  ProfileCardExport: () => <div data-testid="profile-card-export" />,
}));

const mockNavigate = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

const baseUser = {
  id: "u1",
  username: "testuser",
  email: "test@example.com",
  cf_handle: null,
  cf_handle_verified: false,
  elo: 1500,
  pp: 50,
  tokens: 100,
  is_active: true,
  is_admin: false,
  created_at: "2025-01-01T00:00:00Z",
  updated_at: null,
  last_login_at: null,
};

let mockUser = { ...baseUser };
const mockFetchUser = vi.fn().mockResolvedValue(undefined);

vi.mock("@/stores/auth", () => ({
  useAuthStore: Object.assign(
    vi.fn((selector?: (s: Record<string, unknown>) => unknown) => {
      const state = { user: mockUser, fetchUser: mockFetchUser };
      return selector ? selector(state) : state;
    }),
  ),
}));

// ---------------------------------------------------------------------------
// MSW server
// ---------------------------------------------------------------------------

const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "bypass" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

import ProfilePage from "../ProfilePage";

function renderPage() {
  return render(
    <MemoryRouter>
      <ProfilePage />
    </MemoryRouter>,
  );
}

function mockAllEndpoints(overrides?: Record<string, unknown>) {
  server.use(
    http.get("*/api/v1/auth/elo-history", () =>
      HttpResponse.json({
        success: true,
        data: overrides?.eloHistory ?? [{ date: "2025-06-01", elo: 1500 }],
        message: "ok",
      }),
    ),
    http.get("*/api/v1/auth/settings", () =>
      HttpResponse.json({
        success: true,
        data: { display_mode: "medal" },
        message: "ok",
      }),
    ),
    http.get("*/api/v1/medal/overall", () =>
      HttpResponse.json({
        success: true,
        data: { elo: 1500, medal: { level: "silver", type: "arena" } },
        message: "ok",
      }),
    ),
    http.get("*/api/v1/medal/stats", () =>
      HttpResponse.json({
        success: true,
        data: { stats: {}, total_medals: 5 },
        message: "ok",
      }),
    ),
    http.get("*/api/v1/medal/skills", () =>
      HttpResponse.json({
        success: true,
        data: { skills: [] },
        message: "ok",
      }),
    ),
    http.get("*/api/v1/melo/list", () =>
      HttpResponse.json({
        success: true,
        data: { melos: [{ tag: "dp", elo: 1200, total_submissions: 3 }] },
        message: "ok",
      }),
    ),
    http.get("*/api/v1/checkin/status", () =>
      HttpResponse.json({
        success: true,
        data: { streak_days: 2 },
        message: "ok",
      }),
    ),
    http.get("*/api/v1/auth/pp-rank", () =>
      HttpResponse.json({
        success: true,
        data: { rank: 42, top_percent: 5.0, total_users: 1000 },
        message: "ok",
      }),
    ),
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ProfilePage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUser = { ...baseUser };
    server.resetHandlers();
  });

  // 1. Loading state when user is null
  it("shows loading spinner when user is null", () => {
    mockUser = null as unknown as typeof baseUser;
    mockAllEndpoints();
    renderPage();
    expect(screen.getByTestId("loading-spinner")).toBeInTheDocument();
  });

  // 2. Renders user info
  it("renders username, email, and stats", async () => {
    mockAllEndpoints();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("testuser")).toBeInTheDocument();
    });
    expect(screen.getByText("test@example.com")).toBeInTheDocument();
    expect(screen.getByText("profile:eloRating")).toBeInTheDocument();
    expect(screen.getByText("profile:performancePoints")).toBeInTheDocument();
    expect(screen.getByText("common:tokens")).toBeInTheDocument();
    expect(screen.getByText("1500")).toBeInTheDocument();
    expect(screen.getByText("50")).toBeInTheDocument();
    expect(screen.getByText("100")).toBeInTheDocument();
  });

  // 3. Shows CF handle link when not linked
  it("shows CF bind link when user has no cf_handle", async () => {
    mockUser = { ...baseUser, cf_handle: null };
    mockAllEndpoints();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("profile:linkCF")).toBeInTheDocument();
    });
  });

  // 4. Shows CF handle when linked
  it("shows CF handle when linked and verified", async () => {
    mockUser = { ...baseUser, cf_handle: "cfuser", cf_handle_verified: true };
    mockAllEndpoints();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("cfuser")).toBeInTheDocument();
    });
    expect(screen.getByText("profile:verified")).toBeInTheDocument();
    expect(screen.queryByText("profile:linkCF")).not.toBeInTheDocument();
  });

  // 5. Edit profile flow
  it("enters edit mode, changes username, and saves", async () => {
    mockAllEndpoints();
    server.use(
      http.put("*/api/v1/auth/profile", () =>
        HttpResponse.json({ success: true, data: {}, message: "ok" }),
      ),
    );
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("testuser")).toBeInTheDocument();
    });

    await user.click(screen.getByText("profile:editProfile"));
    expect(screen.getByDisplayValue("testuser")).toBeInTheDocument();

    const usernameInput = screen.getByDisplayValue("testuser");
    await user.clear(usernameInput);
    await user.type(usernameInput, "newusername");
    await user.click(screen.getByText("common:save"));

    await waitFor(() => {
      expect(screen.getByText("profile:profileUpdated")).toBeInTheDocument();
    });
  });

  // 6. Edit profile failure
  it("shows error when save fails", async () => {
    mockAllEndpoints();
    server.use(
      http.put("*/api/v1/auth/profile", () =>
        HttpResponse.json(
          { success: false, error: { code: "ERR", message: "Update failed" } },
          { status: 400 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("testuser")).toBeInTheDocument();
    });

    await user.click(screen.getByText("profile:editProfile"));
    // Change username to trigger the API call
    const usernameInput = screen.getByDisplayValue("testuser");
    await user.clear(usernameInput);
    await user.type(usernameInput, "newuser");
    await user.click(screen.getByText("common:save"));

    await waitFor(() => {
      expect(screen.getByText("Update failed")).toBeInTheDocument();
    });
  });

  // 7. Cancel edit
  it("cancels edit mode without saving", async () => {
    mockAllEndpoints();
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("testuser")).toBeInTheDocument();
    });

    await user.click(screen.getByText("profile:editProfile"));
    expect(screen.getByDisplayValue("testuser")).toBeInTheDocument();

    await user.click(screen.getByText("common:cancel"));
    expect(screen.queryByDisplayValue("testuser")).not.toBeInTheDocument();
  });

  // 8. Elo chart renders with data
  it("renders Elo chart after data loads", async () => {
    mockAllEndpoints();
    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("elo-chart")).toBeInTheDocument();
    });
  });

  // 9. Elo chart error state
  it("shows error message when Elo history fails to load", async () => {
    mockAllEndpoints();
    server.use(
      http.get("*/api/v1/auth/elo-history", () =>
        HttpResponse.json({ success: false }, { status: 500 }),
      ),
    );
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("profile:failedLoadElo")).toBeInTheDocument();
    });
  });

  // 10. PP rank data renders
  it("renders PP global ranking section", async () => {
    mockAllEndpoints();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("profile:ppGlobalRanking")).toBeInTheDocument();
    });
    expect(screen.getByText("profile:ppRankValue")).toBeInTheDocument();
  });

  // 11. Navigate to leaderboard
  it("navigates to leaderboard on button click", async () => {
    mockAllEndpoints();
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("profile:viewLeaderboard")).toBeInTheDocument();
    });

    await user.click(screen.getByText("profile:viewLeaderboard"));
    expect(mockNavigate).toHaveBeenCalledWith("/ranking");
  });

  // 12. Navigate to CF bind
  it("navigates to CF bind on button click", async () => {
    mockUser = { ...baseUser, cf_handle: null };
    mockAllEndpoints();
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("profile:bindHandle")).toBeInTheDocument();
    });

    await user.click(screen.getByText("profile:bindHandle"));
    expect(mockNavigate).toHaveBeenCalledWith("/profile/cf-bind");
  });
});
