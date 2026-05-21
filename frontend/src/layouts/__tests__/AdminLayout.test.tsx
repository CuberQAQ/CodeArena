import { describe, it, expect, vi } from "vitest";
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

const mockNavigate = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

vi.mock("@/stores/auth", () => ({
  useAuthStore: (selector: (s: Record<string, unknown>) => unknown) =>
    selector({
      user: { id: "admin-1", username: "admin", is_admin: true },
    }),
}));

// ---------------------------------------------------------------------------
// Import SUT
// ---------------------------------------------------------------------------

import { AdminLayout } from "@/layouts/AdminLayout";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function renderWithRouter() {
  return render(
    <MemoryRouter initialEntries={["/admin"]}>
      <Routes>
        <Route element={<AdminLayout />}>
          <Route path="/admin" element={<div>Overview Page</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("AdminLayout", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders admin panel brand", () => {
    renderWithRouter();
    // nav:adminPanel appears in both sidebar and mobile header
    const brands = screen.getAllByText("nav:adminPanel");
    expect(brands.length).toBeGreaterThanOrEqual(1);
  });

  it("renders navigation items", () => {
    renderWithRouter();
    expect(screen.getByText("nav:overview")).toBeInTheDocument();
    expect(screen.getByText("nav:configuration")).toBeInTheDocument();
  });

  it("renders user info", () => {
    renderWithRouter();
    expect(screen.getByText("admin")).toBeInTheDocument();
  });

  it("renders back to app button", () => {
    renderWithRouter();
    expect(screen.getByText("nav:backToApp")).toBeInTheDocument();
  });

  it("renders LanguageSwitcher", () => {
    renderWithRouter();
    expect(screen.getByText("Lang")).toBeInTheDocument();
  });

  it("renders child content via Outlet", () => {
    renderWithRouter();
    expect(screen.getByText("Overview Page")).toBeInTheDocument();
  });

  it("renders admin role indicator for admin user", () => {
    renderWithRouter();
    expect(screen.getByText("nav:administrator")).toBeInTheDocument();
  });

  it("navigates to dashboard on back button click", async () => {
    const user = userEvent.setup();
    renderWithRouter();

    await user.click(screen.getByText("nav:backToApp"));
    expect(mockNavigate).toHaveBeenCalledWith("/dashboard");
  });
});
