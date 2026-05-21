import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
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

vi.mock("@/components/LoadingSpinner", () => ({
  LoadingSpinner: ({ text }: { text?: string }) => (
    <div data-testid="loading-spinner">{text ?? "Loading..."}</div>
  ),
}));

const mockAuthStore = {
  isAuthenticated: false,
  isLoading: false,
  user: null as { is_admin: boolean; id: string } | null,
};

vi.mock("@/stores/auth", () => ({
  useAuthStore: (selector: (s: typeof mockAuthStore) => unknown) =>
    selector(mockAuthStore),
}));

// ---------------------------------------------------------------------------
// Import SUT
// ---------------------------------------------------------------------------

import { AdminRoute } from "@/components/AdminRoute";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function renderWithRouter(initialEntry = "/admin/secret") {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route
          path="/admin/secret"
          element={
            <AdminRoute>
              <div>Admin Content</div>
            </AdminRoute>
          }
        />
        <Route path="/" element={<div>Login Page</div>} />
        <Route path="/dashboard" element={<div>Dashboard</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("AdminRoute", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockAuthStore.isAuthenticated = false;
    mockAuthStore.isLoading = false;
    mockAuthStore.user = null;
  });

  it("shows loading spinner when isLoading is true", () => {
    mockAuthStore.isLoading = true;
    renderWithRouter();
    expect(screen.getByTestId("loading-spinner")).toBeInTheDocument();
  });

  it("redirects to login when not authenticated", () => {
    mockAuthStore.isLoading = false;
    mockAuthStore.isAuthenticated = false;
    renderWithRouter();
    expect(screen.queryByText("Admin Content")).not.toBeInTheDocument();
    expect(screen.getByText("Login Page")).toBeInTheDocument();
  });

  it("redirects to dashboard when authenticated but not admin", () => {
    mockAuthStore.isLoading = false;
    mockAuthStore.isAuthenticated = true;
    mockAuthStore.user = { is_admin: false, id: "user-1" };
    renderWithRouter();
    expect(screen.queryByText("Admin Content")).not.toBeInTheDocument();
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
  });

  it("renders children when authenticated and admin", () => {
    mockAuthStore.isLoading = false;
    mockAuthStore.isAuthenticated = true;
    mockAuthStore.user = { is_admin: true, id: "admin-1" };
    renderWithRouter();
    expect(screen.getByText("Admin Content")).toBeInTheDocument();
  });
});
