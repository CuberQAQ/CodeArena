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
    t: (key: string) => key,
    i18n: { language: "en" },
  }),
}));

vi.mock("@/components/LoadingSpinner", () => ({
  LoadingSpinner: ({ text }: { text?: string }) => (
    <div data-testid="loading-spinner">{text ?? "Loading..."}</div>
  ),
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

import SettingsPage from "../SettingsPage";

function renderPage() {
  return render(
    <MemoryRouter>
      <SettingsPage />
    </MemoryRouter>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("SettingsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.resetHandlers();
  });

  // 1. Loading state
  it("shows loading spinner initially", () => {
    server.use(
      http.get("*/api/v1/auth/settings", async () => {
        await new Promise(() => {});
      }),
    );
    renderPage();
    expect(screen.getByTestId("loading-spinner")).toBeInTheDocument();
  });

  // 2. Renders settings with default medal mode
  it("renders settings page with medal mode selected", async () => {
    server.use(
      http.get("*/api/v1/auth/settings", () =>
        HttpResponse.json({ success: true, data: { display_mode: "medal" }, message: "ok" }),
      ),
    );
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("medal:settings.title")).toBeInTheDocument();
    });

    const medalRadio = screen.getByDisplayValue("medal") as HTMLInputElement;
    const cfTierRadio = screen.getByDisplayValue("cf_tier") as HTMLInputElement;
    expect(medalRadio.checked).toBe(true);
    expect(cfTierRadio.checked).toBe(false);
  });

  // 3. Renders with cf_tier mode
  it("renders settings page with cf_tier mode selected", async () => {
    server.use(
      http.get("*/api/v1/auth/settings", () =>
        HttpResponse.json({ success: true, data: { display_mode: "cf_tier" }, message: "ok" }),
      ),
    );
    renderPage();

    await waitFor(() => {
      const cfTierRadio = screen.getByDisplayValue("cf_tier") as HTMLInputElement;
      expect(cfTierRadio.checked).toBe(true);
    });
  });

  // 4. Falls back to medal on API error
  it("defaults to medal mode when settings fetch fails", async () => {
    server.use(
      http.get("*/api/v1/auth/settings", () =>
        HttpResponse.json({ success: false }, { status: 500 }),
      ),
    );
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("medal:settings.title")).toBeInTheDocument();
    });
    const medalRadio = screen.getByDisplayValue("medal") as HTMLInputElement;
    expect(medalRadio.checked).toBe(true);
  });

  // 5. Switch display mode
  it("switches display mode radio on click", async () => {
    server.use(
      http.get("*/api/v1/auth/settings", () =>
        HttpResponse.json({ success: true, data: { display_mode: "medal" }, message: "ok" }),
      ),
    );
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("medal:settings.title")).toBeInTheDocument();
    });

    await user.click(screen.getByDisplayValue("cf_tier"));
    const cfTierRadio = screen.getByDisplayValue("cf_tier") as HTMLInputElement;
    expect(cfTierRadio.checked).toBe(true);
  });

  // 6. Save successfully
  it("saves settings and shows success message", async () => {
    server.use(
      http.get("*/api/v1/auth/settings", () =>
        HttpResponse.json({ success: true, data: { display_mode: "medal" }, message: "ok" }),
      ),
      http.put("*/api/v1/auth/settings", () =>
        HttpResponse.json({ success: true, data: {}, message: "ok" }),
      ),
    );
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("common:save")).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: /common:save/i }));

    await waitFor(() => {
      expect(screen.getByText("medal:settings.saved")).toBeInTheDocument();
    });
  });

  // 7. Save failure
  it("shows error when save fails", async () => {
    server.use(
      http.get("*/api/v1/auth/settings", () =>
        HttpResponse.json({ success: true, data: { display_mode: "medal" }, message: "ok" }),
      ),
      http.put("*/api/v1/auth/settings", () =>
        HttpResponse.json(
          { success: false, error: { code: "ERR", message: "Failed to save" } },
          { status: 500 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("common:save")).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: /common:save/i }));

    await waitFor(() => {
      expect(screen.getByText("Failed to save")).toBeInTheDocument();
    });
  });
});
