import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { Outlet } from "react-router-dom";

// ---------------------------------------------------------------------------
// Mocks - must come before the import
// ---------------------------------------------------------------------------

vi.mock("@/stores/auth", () => ({
  useAuthStore: vi.fn((selector: (s: Record<string, unknown>) => unknown) =>
    selector({ hydrate: vi.fn() }),
  ),
}));

vi.mock("@/components/ErrorBoundary", () => ({
  ErrorBoundary: ({ children }: React.PropsWithChildren) => <>{children}</>,
}));

vi.mock("@/components/ProtectedRoute", () => ({
  ProtectedRoute: ({ children }: React.PropsWithChildren) => <>{children}</>,
}));

vi.mock("@/components/AdminRoute", () => ({
  AdminRoute: ({ children }: React.PropsWithChildren) => <>{children}</>,
}));

vi.mock("@/layouts/AuthLayout", () => ({
  AuthLayout: () => (
    <div data-testid="auth-layout">
      <Outlet />
    </div>
  ),
}));

vi.mock("@/layouts/MainLayout", () => ({
  MainLayout: () => (
    <div data-testid="main-layout">
      <Outlet />
    </div>
  ),
}));

vi.mock("@/layouts/AdminLayout", () => ({
  AdminLayout: () => (
    <div data-testid="admin-layout">
      <Outlet />
    </div>
  ),
}));

// Page mocks with unique data-testid identifiers
vi.mock("@/pages/LoginPage", () => ({
  default: () => <div data-testid="page-login">Login Page</div>,
}));
vi.mock("@/pages/RegisterPage", () => ({
  default: () => <div data-testid="page-register">Register Page</div>,
}));
vi.mock("@/pages/DashboardPage", () => ({
  default: () => <div data-testid="page-dashboard">Dashboard Page</div>,
}));
vi.mock("@/pages/ChallengePage", () => ({
  default: () => <div data-testid="page-challenge">Challenge Page</div>,
}));
vi.mock("@/pages/challenge/PvEChallengePage", () => ({
  default: () => <div data-testid="page-pve">PvE Challenge Page</div>,
}));
vi.mock("@/pages/FreePlayPage", () => ({
  default: () => <div data-testid="page-freeplay">FreePlay Page</div>,
}));
vi.mock("@/pages/FreePlaySessionPage", () => ({
  default: () => <div data-testid="page-freeplay-session">FreePlay Session Page</div>,
}));
vi.mock("@/pages/TrainingPage", () => ({
  default: () => <div data-testid="page-training">Training Page</div>,
}));
vi.mock("@/pages/TrainingDetailPage", () => ({
  default: () => <div data-testid="page-training-detail">Training Detail Page</div>,
}));
vi.mock("@/pages/ContestPage", () => ({
  default: () => <div data-testid="page-contest">Contest Page</div>,
}));
vi.mock("@/pages/ContestDetailPage", () => ({
  default: () => <div data-testid="page-contest-detail">Contest Detail Page</div>,
}));
vi.mock("@/pages/ProfilePage", () => ({
  default: () => <div data-testid="page-profile">Profile Page</div>,
}));
vi.mock("@/pages/CFBindPage", () => ({
  default: () => <div data-testid="page-cfbind">CFBind Page</div>,
}));
vi.mock("@/pages/RankingPage", () => ({
  default: () => <div data-testid="page-ranking">Ranking Page</div>,
}));
vi.mock("@/pages/AdminOverviewPage", () => ({
  default: () => <div data-testid="page-admin">Admin Overview Page</div>,
}));
vi.mock("@/pages/AdminConfigPage", () => ({
  default: () => <div data-testid="page-admin-config">Admin Config Page</div>,
}));
vi.mock("@/pages/SettingsPage", () => ({
  default: () => <div data-testid="page-settings">Settings Page</div>,
}));

// ---------------------------------------------------------------------------
// Import SUT
// ---------------------------------------------------------------------------

import App from "@/App";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("App", () => {
  it("renders without crashing", () => {
    const { container } = render(<App />);
    expect(container).toBeInTheDocument();
  });

  it("shows Login Page at root route", () => {
    render(<App />);
    expect(screen.getByTestId("page-login")).toBeInTheDocument();
  });

  it("wraps auth routes in AuthLayout", () => {
    render(<App />);
    expect(screen.getByTestId("auth-layout")).toBeInTheDocument();
  });

  it("renders main layout for protected routes", () => {
    window.history.replaceState({}, "", "/dashboard");
    render(<App />);
    expect(screen.getByTestId("main-layout")).toBeInTheDocument();
    expect(screen.getByTestId("page-dashboard")).toBeInTheDocument();
  });

  it("renders admin layout for admin routes", () => {
    window.history.replaceState({}, "", "/admin");
    render(<App />);
    expect(screen.getByTestId("admin-layout")).toBeInTheDocument();
    expect(screen.getByTestId("page-admin")).toBeInTheDocument();
  });

  it("renders training page at /training route", () => {
    window.history.replaceState({}, "", "/training");
    render(<App />);
    expect(screen.getByTestId("page-training")).toBeInTheDocument();
  });

  it("renders profile page at /profile route", () => {
    window.history.replaceState({}, "", "/profile");
    render(<App />);
    expect(screen.getByTestId("page-profile")).toBeInTheDocument();
  });

  it("renders ranking page at /ranking route", () => {
    window.history.replaceState({}, "", "/ranking");
    render(<App />);
    expect(screen.getByTestId("page-ranking")).toBeInTheDocument();
  });

  it("renders settings page at /settings route", () => {
    window.history.replaceState({}, "", "/settings");
    render(<App />);
    expect(screen.getByTestId("page-settings")).toBeInTheDocument();
  });
});
