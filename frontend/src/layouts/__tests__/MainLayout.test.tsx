import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
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

vi.mock("@/components/Avatar", () => ({
  Avatar: ({ userId }: { userId?: string }) => (
    <div data-testid="avatar">{userId ?? "no-id"}</div>
  ),
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
vi.mock("@/stores/auth", () => ({
  useAuthStore: (selector: (s: Record<string, unknown>) => unknown) =>
    selector({
      user: {
        id: "user-1",
        username: "testuser",
        elo: 1500,
        tokens: 50,
      },
      logout: mockLogout,
    }),
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
    expect(screen.getByText("testuser")).toBeInTheDocument();
  });

  it("renders avatar", () => {
    renderWithRouter();
    expect(screen.getByTestId("avatar")).toBeInTheDocument();
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
    expect(screen.getByText("Lang")).toBeInTheDocument();
  });

  it("calls logout and navigates on logout click", async () => {
    const user = userEvent.setup();
    renderWithRouter();

    await user.click(screen.getByText("nav:logout"));
    expect(mockLogout).toHaveBeenCalled();
    expect(mockNavigate).toHaveBeenCalledWith("/");
  });

  it("renders Elo and tokens info", () => {
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
    // The overlay div contains "bg-black/50" in its className
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
});
