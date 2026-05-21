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

const mockRegister = vi.fn();
const mockNavigate = vi.fn();

vi.mock("@/stores/auth", () => ({
  useAuthStore: vi.fn((selector: (s: Record<string, unknown>) => unknown) =>
    selector({ register: mockRegister }),
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

import RegisterPage from "../RegisterPage";

function renderPage() {
  return render(
    <MemoryRouter>
      <RegisterPage />
    </MemoryRouter>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("RegisterPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // 1. Renders form elements
  it("renders all form fields and submit button", () => {
    renderPage();
    expect(screen.getByLabelText("register.username")).toBeInTheDocument();
    expect(screen.getByLabelText("register.email")).toBeInTheDocument();
    expect(screen.getByLabelText("register.password")).toBeInTheDocument();
    expect(screen.getByLabelText("register.confirmPassword")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "register.createAccount" })).toBeInTheDocument();
  });

  // 2. Renders title and subtitle
  it("renders title and subtitle", () => {
    renderPage();
    expect(screen.getByText("register.title")).toBeInTheDocument();
    expect(screen.getByText("register.subtitle")).toBeInTheDocument();
  });

  // 3. Renders link to login page
  it("renders link to login page", () => {
    renderPage();
    const link = screen.getByText("register.signIn");
    expect(link).toBeInTheDocument();
    expect(link.closest("a")).toHaveAttribute("href", "/");
  });

  // 4. Shows password mismatch error
  it("shows error when passwords do not match", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByLabelText("register.username"), "testuser");
    await user.type(screen.getByLabelText("register.email"), "test@example.com");
    await user.type(screen.getByLabelText("register.password"), "password123");
    await user.type(screen.getByLabelText("register.confirmPassword"), "different123");
    await user.click(screen.getByRole("button", { name: "register.createAccount" }));

    expect(screen.getByText("register.passwordMismatch")).toBeInTheDocument();
    expect(mockRegister).not.toHaveBeenCalled();
  });

  // 5. Successful registration
  it("calls register and navigates to dashboard on success", async () => {
    mockRegister.mockResolvedValue(undefined);
    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByLabelText("register.username"), "testuser");
    await user.type(screen.getByLabelText("register.email"), "test@example.com");
    await user.type(screen.getByLabelText("register.password"), "password123");
    await user.type(screen.getByLabelText("register.confirmPassword"), "password123");
    await user.click(screen.getByRole("button", { name: "register.createAccount" }));

    await waitFor(() => {
      expect(mockRegister).toHaveBeenCalledWith("testuser", "test@example.com", "password123");
    });
    expect(mockNavigate).toHaveBeenCalledWith("/dashboard");
  });

  // 6. Failed registration shows error
  it("shows error message on registration failure", async () => {
    mockRegister.mockRejectedValue({
      response: { data: { error: { message: "Username taken" } } },
    });
    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByLabelText("register.username"), "taken");
    await user.type(screen.getByLabelText("register.email"), "a@b.com");
    await user.type(screen.getByLabelText("register.password"), "password123");
    await user.type(screen.getByLabelText("register.confirmPassword"), "password123");
    await user.click(screen.getByRole("button", { name: "register.createAccount" }));

    await waitFor(() => {
      expect(screen.getByText("Username taken")).toBeInTheDocument();
    });
    expect(mockNavigate).not.toHaveBeenCalled();
  });

  // 7. Shows loading state during registration
  it("shows loading text and disables button while registering", async () => {
    let resolveRegister: () => void;
    mockRegister.mockReturnValue(new Promise<void>((resolve) => { resolveRegister = resolve; }));
    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByLabelText("register.username"), "testuser");
    await user.type(screen.getByLabelText("register.email"), "a@b.com");
    await user.type(screen.getByLabelText("register.password"), "password123");
    await user.type(screen.getByLabelText("register.confirmPassword"), "password123");
    await user.click(screen.getByRole("button", { name: "register.createAccount" }));

    expect(screen.getByText("register.creatingAccount")).toBeInTheDocument();
    resolveRegister!();
  });
});
