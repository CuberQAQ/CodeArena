import { describe, it, expect, vi, beforeAll, afterAll, afterEach, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
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
      if (params) {
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

vi.mock("@/utils", () => ({
  extractApiError: (err: unknown, fallback: string) => {
    const e = err as { response?: { data?: { error?: { message?: string } } } };
    return e?.response?.data?.error?.message ?? fallback;
  },
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

import CFBindPage from "../CFBindPage";

function renderPage() {
  return render(
    <MemoryRouter>
      <CFBindPage />
    </MemoryRouter>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("CFBindPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUser = { ...baseUser };
    server.resetHandlers();
  });

  // 1. Renders bind form when no CF handle
  it("renders bind form when user has no CF handle", () => {
    renderPage();
    expect(screen.getByText("cfBind.bindCFHandle")).toBeInTheDocument();
    expect(screen.getByLabelText("cfBind.codeforcesHandle")).toBeInTheDocument();
    expect(screen.getByText("cfBind.bindHandle")).toBeInTheDocument();
  });

  // 2. Shows back to profile button
  it("shows back to profile button", () => {
    renderPage();
    expect(screen.getByText("cfBind.backToProfile")).toBeInTheDocument();
  });

  // 3. Successful bind shows verification code
  it("binds CF handle and shows verification code", async () => {
    server.use(
      http.post("*/api/v1/cf-handle/bind", () =>
        HttpResponse.json({
          success: true,
          data: { verification_code: "ABC123" },
          message: "ok",
        }),
      ),
    );
    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByLabelText("cfBind.codeforcesHandle"), "cfuser");
    await user.click(screen.getByText("cfBind.bindHandle"));

    await waitFor(() => {
      expect(screen.getByText("ABC123")).toBeInTheDocument();
    });
    expect(screen.getByText("cfBind.verifyYourHandle")).toBeInTheDocument();
  });

  // 4. Bind failure shows error
  it("shows error when bind fails", async () => {
    server.use(
      http.post("*/api/v1/cf-handle/bind", () =>
        HttpResponse.json(
          { success: false, error: { code: "ERR", message: "Handle not found" } },
          { status: 400 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByLabelText("cfBind.codeforcesHandle"), "baduser");
    await user.click(screen.getByText("cfBind.bindHandle"));

    await waitFor(() => {
      expect(screen.getByText("Handle not found")).toBeInTheDocument();
    });
  });

  // 5. Already verified state shows unbind button
  it("shows verified state when CF handle is already verified", () => {
    mockUser = { ...baseUser, cf_handle: "cfuser", cf_handle_verified: true };
    renderPage();

    expect(screen.getByText("cfBind.cfHandleBound")).toBeInTheDocument();
    expect(screen.getByText("cfBind.unbindHandle")).toBeInTheDocument();
  });

  // 6. Pending binding shows pending verification message
  it("shows pending verification message when handle is pending", () => {
    mockUser = { ...baseUser, cf_handle: "cfuser", cf_handle_verified: false };
    renderPage();

    expect(screen.getByText("cfBind.pendingVerification")).toBeInTheDocument();
  });

  // 7. Unbind flow
  it("unbinds CF handle and calls fetchUser", async () => {
    mockUser = { ...baseUser, cf_handle: "cfuser", cf_handle_verified: true };
    server.use(
      http.delete("*/api/v1/cf-handle/unbind", () =>
        HttpResponse.json({ success: true, data: {}, message: "ok" }),
      ),
    );
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByText("cfBind.unbindHandle"));

    await waitFor(() => {
      expect(mockFetchUser).toHaveBeenCalled();
    });
  });

  // 8. Unbind failure shows error
  it("shows error when unbind fails", async () => {
    mockUser = { ...baseUser, cf_handle: "cfuser", cf_handle_verified: true };
    server.use(
      http.delete("*/api/v1/cf-handle/unbind", () =>
        HttpResponse.json(
          { success: false, error: { code: "ERR", message: "Unbind failed" } },
          { status: 500 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByText("cfBind.unbindHandle"));

    await waitFor(() => {
      expect(screen.getByText("Unbind failed")).toBeInTheDocument();
    });
  });

  // 9. Verify button triggers verify API
  it("calls verify API after binding", async () => {
    server.use(
      http.post("*/api/v1/cf-handle/bind", () =>
        HttpResponse.json({
          success: true,
          data: { verification_code: "XYZ789" },
          message: "ok",
        }),
      ),
      http.post("*/api/v1/cf-handle/verify", () =>
        HttpResponse.json({ success: true, data: {}, message: "ok" }),
      ),
    );
    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByLabelText("cfBind.codeforcesHandle"), "cfuser");
    await user.click(screen.getByText("cfBind.bindHandle"));

    await waitFor(() => {
      expect(screen.getByText("cfBind.verify")).toBeInTheDocument();
    });

    await user.click(screen.getByText("cfBind.verify"));

    await waitFor(() => {
      expect(mockFetchUser).toHaveBeenCalled();
    });
  });

  // 10. Back button navigates to profile
  it("navigates to profile on back button click", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByText("cfBind.backToProfile"));
    expect(mockNavigate).toHaveBeenCalledWith("/profile");
  });

  // 11. Copy verification code to clipboard (covers handleCopy function, lines 43-59)
  it("copies verification code when copy button is clicked", async () => {
    server.use(
      http.post("*/api/v1/cf-handle/bind", () =>
        HttpResponse.json({
          success: true,
          data: { verification_code: "COPY123" },
          message: "ok",
        }),
      ),
    );
    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByLabelText("cfBind.codeforcesHandle"), "cfuser");
    await user.click(screen.getByText("cfBind.bindHandle"));

    await waitFor(() => {
      expect(screen.getByText("COPY123")).toBeInTheDocument();
    });

    // Click the copy button (icon button) -- this triggers handleCopy
    const copyBtn = screen.getByTitle("cfBind.copyVerificationCode");
    await user.click(copyBtn);

    // The handleCopy function should have been called
    // In jsdom, clipboard.writeText throws, so it falls through to the fallback
    // Check that the "copied" state appears (line 280: copied && ...)
    await waitFor(() => {
      expect(screen.getByText("common:copied")).toBeInTheDocument();
    });
  });

  // 12. Back button in pending step resets to idle (covers lines 338-341)
  it("resets to bind form when back button clicked during verification", async () => {
    server.use(
      http.post("*/api/v1/cf-handle/bind", () =>
        HttpResponse.json({
          success: true,
          data: { verification_code: "BACK123" },
          message: "ok",
        }),
      ),
    );
    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByLabelText("cfBind.codeforcesHandle"), "cfuser");
    await user.click(screen.getByText("cfBind.bindHandle"));

    await waitFor(() => {
      expect(screen.getByText("BACK123")).toBeInTheDocument();
    });

    // Click the "back" button in the verification step
    await user.click(screen.getByText("common:back"));

    // Should show the input form again
    await waitFor(() => {
      expect(screen.getByLabelText("cfBind.codeforcesHandle")).toBeInTheDocument();
    });
  });

  // 13. Submit with empty handle does not call API (covers line 64)
  it("does not submit when cfHandle is empty", async () => {
    const user = userEvent.setup();
    renderPage();

    // Click bind without entering a handle - the button should be disabled
    const bindBtn = screen.getByText("cfBind.bindHandle");
    expect(bindBtn).toBeDisabled();
  });

  // 14. Verify failure shows error (covers lines 93-94)
  it("shows error when verify fails", async () => {
    server.use(
      http.post("*/api/v1/cf-handle/bind", () =>
        HttpResponse.json({
          success: true,
          data: { verification_code: "FAIL123" },
          message: "ok",
        }),
      ),
      http.post("*/api/v1/cf-handle/verify", () =>
        HttpResponse.json(
          { success: false, error: { code: "ERR", message: "Verification failed" } },
          { status: 400 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByLabelText("cfBind.codeforcesHandle"), "cfuser");
    await user.click(screen.getByText("cfBind.bindHandle"));

    await waitFor(() => {
      expect(screen.getByText("cfBind.verify")).toBeInTheDocument();
    });

    await user.click(screen.getByText("cfBind.verify"));

    await waitFor(() => {
      expect(screen.getByText("Verification failed")).toBeInTheDocument();
    });
  });
});
