import { describe, it, expect, vi } from "vitest";
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

vi.mock("@/components/LanguageSwitcher", () => ({
  LanguageSwitcher: () => <button>Lang</button>,
}));

// ---------------------------------------------------------------------------
// Import SUT
// ---------------------------------------------------------------------------

import { AuthLayout } from "@/layouts/AuthLayout";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function renderWithRouter() {
  return render(
    <MemoryRouter initialEntries={["/login"]}>
      <Routes>
        <Route element={<AuthLayout />}>
          <Route path="/login" element={<div>Login Form</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("AuthLayout", () => {
  it("renders Code Arena brand", () => {
    renderWithRouter();
    expect(screen.getByText("Code Arena")).toBeInTheDocument();
  });

  it("renders platform slogan", () => {
    renderWithRouter();
    expect(screen.getByText("platformSlogan")).toBeInTheDocument();
  });

  it("renders LanguageSwitcher", () => {
    renderWithRouter();
    expect(screen.getByText("Lang")).toBeInTheDocument();
  });

  it("renders child content via Outlet", () => {
    renderWithRouter();
    expect(screen.getByText("Login Form")).toBeInTheDocument();
  });
});
