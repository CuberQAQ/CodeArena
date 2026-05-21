import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: "en" },
  }),
}));

const mockLogin = vi.fn();
const mockNavigate = vi.fn();

vi.mock("@/stores/auth", () => ({
  useAuthStore: vi.fn((selector: (s: Record<string, unknown>) => unknown) =>
    selector({ login: mockLogin }),
  ),
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

vi.mock("@/utils", () => ({
  extractApiError: (err: unknown, fallback: string) => {
    const e = err as { response?: { data?: { error?: { message?: string } } } };
    return e?.response?.data?.error?.message ?? fallback;
  },
}));

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

import LoginPage from "../LoginPage";

function renderPage() {
  return render(
    <MemoryRouter>
      <LoginPage />
    </MemoryRouter>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("LoginPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // 1. Renders form elements
  it("renders email input, password input, and submit button", () => {
    renderPage();
    expect(screen.getByLabelText("login.email")).toBeInTheDocument();
    expect(screen.getByLabelText("login.password")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "login.signIn" })).toBeInTheDocument();
  });

  // 2. Renders title and subtitle
  it("renders title and subtitle", () => {
    renderPage();
    expect(screen.getByText("login.title")).toBeInTheDocument();
    expect(screen.getByText("login.subtitle")).toBeInTheDocument();
  });

  // 3. Renders link to register page
  it("renders link to register page", () => {
    renderPage();
    const link = screen.getByText("login.createOne");
    expect(link).toBeInTheDocument();
    expect(link.closest("a")).toHaveAttribute("href", "/register");
  });

  // 4. Successful login
  it("calls login and navigates to dashboard on success", async () => {
    mockLogin.mockResolvedValue(undefined);
    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByLabelText("login.email"), "test@example.com");
    await user.type(screen.getByLabelText("login.password"), "password123");
    await user.click(screen.getByRole("button", { name: "login.signIn" }));

    await waitFor(() => {
      expect(mockLogin).toHaveBeenCalledWith("test@example.com", "password123");
    });
    expect(mockNavigate).toHaveBeenCalledWith("/dashboard");
  });

  // 5. Failed login shows error
  it("shows error message on login failure", async () => {
    mockLogin.mockRejectedValue({
      response: { data: { error: { message: "Invalid credentials" } } },
    });
    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByLabelText("login.email"), "bad@example.com");
    await user.type(screen.getByLabelText("login.password"), "wrong");
    await user.click(screen.getByRole("button", { name: "login.signIn" }));

    await waitFor(() => {
      expect(screen.getByText("Invalid credentials")).toBeInTheDocument();
    });
    expect(mockNavigate).not.toHaveBeenCalled();
  });

  // 6. Shows loading state on submit button while logging in
  it("shows loading text and disables button while logging in", async () => {
    let resolveLogin: () => void;
    mockLogin.mockReturnValue(new Promise<void>((resolve) => { resolveLogin = resolve; }));
    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByLabelText("login.email"), "test@example.com");
    await user.type(screen.getByLabelText("login.password"), "password123");
    await user.click(screen.getByRole("button", { name: "login.signIn" }));

    expect(screen.getByText("login.signingIn")).toBeInTheDocument();
    resolveLogin!();
  });

  // 7. Error is cleared on next submit attempt
  it("clears error on next submit attempt", async () => {
    mockLogin.mockRejectedValueOnce({
      response: { data: { error: { message: "Invalid credentials" } } },
    });
    mockLogin.mockResolvedValueOnce(undefined);
    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByLabelText("login.email"), "a@b.com");
    await user.type(screen.getByLabelText("login.password"), "pw");
    await user.click(screen.getByRole("button", { name: "login.signIn" }));

    await waitFor(() => {
      expect(screen.getByText("Invalid credentials")).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: "login.signIn" }));

    await waitFor(() => {
      expect(screen.queryByText("Invalid credentials")).not.toBeInTheDocument();
    });
  });
});
