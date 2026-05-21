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
  user: null,
};

vi.mock("@/stores/auth", () => ({
  useAuthStore: (selector: (s: typeof mockAuthStore) => unknown) =>
    selector(mockAuthStore),
}));

// ---------------------------------------------------------------------------
// Import SUT
// ---------------------------------------------------------------------------

import { ProtectedRoute } from "@/components/ProtectedRoute";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function renderWithRouter(initialEntry = "/protected") {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route
          path="/protected"
          element={
            <ProtectedRoute>
              <div>Protected Content</div>
            </ProtectedRoute>
          }
        />
        <Route path="/" element={<div>Login Page</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ProtectedRoute", () => {
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
    expect(screen.getByText("common:loading")).toBeInTheDocument();
  });

  it("redirects to login when not authenticated", () => {
    mockAuthStore.isLoading = false;
    mockAuthStore.isAuthenticated = false;
    renderWithRouter();
    expect(screen.queryByText("Protected Content")).not.toBeInTheDocument();
    expect(screen.getByText("Login Page")).toBeInTheDocument();
  });

  it("renders children when authenticated", () => {
    mockAuthStore.isLoading = false;
    mockAuthStore.isAuthenticated = true;
    renderWithRouter();
    expect(screen.getByText("Protected Content")).toBeInTheDocument();
  });
});
