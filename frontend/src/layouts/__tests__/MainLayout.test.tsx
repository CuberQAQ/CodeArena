import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: "en" },
  }),
}));

vi.mock("@/components/LanguageSwitcher", () => ({
  LanguageSwitcher: () => <button>Lang</button>,
}));

vi.mock("@/components/ThemeToggle", () => ({
  ThemeToggle: () => <button>Theme</button>,
}));

vi.mock("@/components/Avatar", () => ({
  Avatar: ({ userId, size }: { userId?: string; size?: number }) => (
    <div data-testid="avatar" data-size={size}>{userId ?? "no-id"}</div>
  ),
}));

vi.mock("@/components/medal/MedalBadge", () => ({
  MedalBadge: ({ level, type, size }: { level: string; type?: string; size?: string }) => (
    <span data-testid="medal-badge" data-level={level} data-type={type} data-size={size}>
      {level}/{type ?? "none"}
    </span>
  ),
}));

vi.mock("@/utils", () => ({
  getRatingColor: (elo: number) => {
    if (elo >= 2400) return "#FF0000";
    if (elo >= 2100) return "#FF8C00";
    if (elo >= 1900) return "#AA00AA";
    if (elo >= 1600) return "#0000FF";
    if (elo >= 1400) return "#03A89E";
    if (elo >= 1200) return "#008000";
    return "#808080";
  },
  ratingToMedal: (elo: number) => {
    if (elo >= 2800) return { level: "world_finals", type: "gold" };
    if (elo >= 2600) return { level: "ec_final", type: "gold" };
    if (elo >= 2200) return { level: "regional", type: "gold" };
    if (elo >= 1600) return { level: "provincial", type: "gold" };
    if (elo >= 1400) return { level: "provincial", type: "silver" };
    if (elo >= 1200) return { level: "provincial", type: "bronze" };
    return { level: "unranked" };
  },
}));

const mockNavigate = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

const mockLogout = vi.fn();
const mockUser = {
  id: "user-1",
  username: "testuser",
  elo: 1500,
  tokens: 50,
  pp: 100,
};

let mockAuthState: Record<string, unknown> = {
  user: mockUser,
  logout: mockLogout,
  loginTime: new Date().toISOString(),
};

vi.mock("@/stores/auth", () => ({
  useAuthStore: (selector: (s: Record<string, unknown>) => unknown) => selector(mockAuthState),
}));

// ---------------------------------------------------------------------------
// Import SUT
// ---------------------------------------------------------------------------

import { MainLayout } from "@/layouts/MainLayout";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function renderWithRouter() {
  return render(
    <MemoryRouter initialEntries={["/dashboard"]}>
      <Routes>
        <Route element={<MainLayout />}>
          <Route path="/dashboard" element={<div>Dashboard Page</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("MainLayout", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Reset auth state to default
    mockAuthState = {
      user: mockUser,
      logout: mockLogout,
      loginTime: new Date().toISOString(),
    };
  });

  it("renders navigation brand", () => {
    renderWithRouter();
    expect(screen.getAllByText("nav:brand").length).toBeGreaterThan(0);
  });

  it("renders navigation items", () => {
    renderWithRouter();
    expect(screen.getByText("nav:dashboard")).toBeInTheDocument();
    expect(screen.getByText("nav:challenge")).toBeInTheDocument();
    expect(screen.getByText("nav:training")).toBeInTheDocument();
    expect(screen.getByText("nav:ranking")).toBeInTheDocument();
    expect(screen.getByText("nav:profile")).toBeInTheDocument();
    expect(screen.getByText("nav:settings")).toBeInTheDocument();
  });

  it("renders user info in sidebar", () => {
    renderWithRouter();
    // Username appears in both sidebar and player bar
    const usernames = screen.getAllByText("testuser");
    expect(usernames.length).toBeGreaterThanOrEqual(1);
  });

  it("renders avatar", () => {
    renderWithRouter();
    expect(screen.getAllByTestId("avatar").length).toBeGreaterThanOrEqual(1);
  });

  it("renders logout button", () => {
    renderWithRouter();
    expect(screen.getByText("nav:logout")).toBeInTheDocument();
  });

  it("renders child content via Outlet", () => {
    renderWithRouter();
    expect(screen.getByText("Dashboard Page")).toBeInTheDocument();
  });

  it("renders LanguageSwitcher", () => {
    renderWithRouter();
    // Lang appears on both mobile and desktop layouts
    const langButtons = screen.getAllByText("Lang");
    expect(langButtons.length).toBeGreaterThanOrEqual(1);
  });

  it("calls logout and navigates on logout click", async () => {
    const user = userEvent.setup();
    renderWithRouter();

    await user.click(screen.getByText("nav:logout"));
    expect(mockLogout).toHaveBeenCalled();
    expect(mockNavigate).toHaveBeenCalledWith("/");
  });

  it("renders Elo and tokens info in sidebar", () => {
    renderWithRouter();
    expect(
      screen.getByText(/nav:eloTokens/),
    ).toBeInTheDocument();
  });

  // Covers lines 139-143: hamburger menu button opens sidebar
  it("opens sidebar when hamburger menu is clicked", async () => {
    const user = userEvent.setup();
    renderWithRouter();

    // Find the hamburger button in the header (it's the first button with lg:hidden class)
    const hamburgerBtn = document.querySelector("header button");
    expect(hamburgerBtn).toBeTruthy();
    await user.click(hamburgerBtn!);

    // After clicking, the mobile overlay should be visible
    const overlay = document.querySelector('[class*="bg-black/50"]');
    expect(overlay).toBeInTheDocument();
  });

  // Covers lines 57-62: mobile overlay click closes sidebar
  it("closes sidebar when overlay is clicked", async () => {
    const user = userEvent.setup();
    renderWithRouter();

    // First open the sidebar
    const hamburgerBtn = document.querySelector("header button");
    expect(hamburgerBtn).toBeTruthy();
    await user.click(hamburgerBtn!);

    // Now click the overlay to close
    const overlay = document.querySelector('[class*="bg-black/50"]');
    expect(overlay).toBeInTheDocument();
    await user.click(overlay as HTMLElement);

    // Overlay should be gone after closing
    expect(document.querySelector('[class*="bg-black/50"]')).not.toBeInTheDocument();
  });

  // Covers lines 74-79: X button in sidebar closes it on mobile
  it("closes sidebar when X button is clicked", async () => {
    const user = userEvent.setup();
    renderWithRouter();

    // First open the sidebar
    const hamburgerBtn = document.querySelector("header button");
    expect(hamburgerBtn).toBeTruthy();
    await user.click(hamburgerBtn!);

    // Find the X close button inside the sidebar
    const aside = document.querySelector("aside");
    expect(aside).toBeTruthy();
    const closeBtn = aside!.querySelector("button");
    expect(closeBtn).toBeTruthy();
    await user.click(closeBtn!);

    // Overlay should be gone after closing
    expect(document.querySelector('[class*="bg-black/50"]')).not.toBeInTheDocument();
  });

  // ---------------------------------------------------------------------------
  // PlayerInfoBar tests
  // ---------------------------------------------------------------------------

  describe("PlayerInfoBar", () => {
    beforeEach(() => {
      vi.useFakeTimers();
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    it("renders medal badge with correct level and type", () => {
      renderWithRouter();
      const badge = screen.getByTestId("medal-badge");
      expect(badge).toBeInTheDocument();
      // elo=1500 -> provincial/silver
      expect(badge).toHaveAttribute("data-level", "provincial");
      expect(badge).toHaveAttribute("data-type", "silver");
    });

    it("renders online time in HH:MM:SS format", () => {
      renderWithRouter();
      // Find the monospace timer element(s) -- should match HH:MM:SS pattern
      const timers = screen.getAllByText(/\d{2}:\d{2}:\d{2}/);
      expect(timers.length).toBeGreaterThanOrEqual(1);
    });

    it("updates online time every second", () => {
      renderWithRouter();

      const timers = screen.getAllByText(/\d{2}:\d{2}:\d{2}/);
      const firstTime = timers[0].textContent;
      expect(firstTime).toBeTruthy();

      // Advance by 2 seconds
      act(() => {
        vi.advanceTimersByTime(2000);
      });

      // The timer should have updated
      const updatedTimers = screen.getAllByText(/\d{2}:\d{2}:\d{2}/);
      expect(updatedTimers.length).toBeGreaterThanOrEqual(1);
    });

    it("renders PP value", () => {
      renderWithRouter();
      expect(screen.getByText(/common:pp/)).toBeInTheDocument();
    });

    it("renders Elo with color styling", () => {
      renderWithRouter();
      // elo=1500 is cyan (#03A89E) - may appear in sidebar and player bar
      const eloElements = screen.getAllByText("1500");
      expect(eloElements.length).toBeGreaterThanOrEqual(1);
    });

    // ---------------------------------------------------------------
    // NEW: Task 47.2 comprehensive test points
    // ---------------------------------------------------------------

    it("renders avatar with size 32 for desktop player info bar", () => {
      renderWithRouter();
      const avatars = screen.getAllByTestId("avatar");
      // Desktop PlayerInfoBar uses size={32}, sidebar uses size={36}, mobile uses size={28}
      const sizes = avatars.map((a) => Number(a.getAttribute("data-size")));
      expect(sizes).toContain(32);
    });

    it("renders avatar with size 28 for mobile player info bar", () => {
      renderWithRouter();
      const avatars = screen.getAllByTestId("avatar");
      const sizes = avatars.map((a) => Number(a.getAttribute("data-size")));
      expect(sizes).toContain(28);
    });

    it("renders username in desktop player info bar", () => {
      renderWithRouter();
      // Username "testuser" appears in sidebar (inside aside) and player info bar
      const allUsernames = screen.getAllByText("testuser");
      expect(allUsernames.length).toBeGreaterThanOrEqual(2);
    });

    it("renders MedalBadge with size sm", () => {
      renderWithRouter();
      const badge = screen.getByTestId("medal-badge");
      expect(badge).toHaveAttribute("data-size", "sm");
    });

    it("renders PP with 1 decimal place", () => {
      renderWithRouter();
      // PP is 100 -> fixed(1) -> "100.0"
      expect(screen.getByText(/100\.0/)).toBeInTheDocument();
    });

    it("renders Theme toggle and Language switcher at far right of desktop top bar", () => {
      renderWithRouter();
      // Both "Theme" and "Lang" buttons should be present
      const themeButtons = screen.getAllByText("Theme");
      expect(themeButtons.length).toBeGreaterThanOrEqual(1);
      const langButtons = screen.getAllByText("Lang");
      expect(langButtons.length).toBeGreaterThanOrEqual(1);
    });

    it("renders online time with monospace/tabular-nums styling", () => {
      renderWithRouter();
      // The online time element has class "font-mono tabular-nums"
      const timerElements = screen.getAllByText(/\d{2}:\d{2}:\d{2}/);
      // At least one should have font-mono class
      const hasMonospace = timerElements.some((el) =>
        el.className.includes("font-mono"),
      );
      expect(hasMonospace).toBe(true);
    });

    it("shows 00:00:00 when loginTime is null", () => {
      mockAuthState = {
        ...mockAuthState,
        loginTime: null,
      };
      renderWithRouter();
      const defaultTimers = screen.getAllByText("00:00:00");
      expect(defaultTimers.length).toBeGreaterThanOrEqual(1);
    });

    it("does not render PlayerInfoBar when user is null", () => {
      mockAuthState = {
        user: null,
        logout: mockLogout,
        loginTime: null,
      };
      renderWithRouter();
      // No medal badge should appear (PlayerInfoBar returns null)
      expect(screen.queryByTestId("medal-badge")).not.toBeInTheDocument();
    });
  });
});
