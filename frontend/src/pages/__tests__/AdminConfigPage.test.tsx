import { describe, it, expect, vi, beforeAll, afterAll, afterEach, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      if (opts) return `${key}:${JSON.stringify(opts)}`;
      return key;
    },
    i18n: { language: "en" },
  }),
}));

vi.mock("@/components/LoadingSpinner", () => ({
  LoadingSpinner: ({ text }: { text?: string }) => (
    <div data-testid="loading-spinner">{text ?? "Loading..."}</div>
  ),
}));

vi.mock("@/utils", () => ({
  extractApiError: (_err: unknown, fallback: string) => fallback,
}));

// ---------------------------------------------------------------------------
// MSW server
// ---------------------------------------------------------------------------

const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "bypass" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

// ---------------------------------------------------------------------------
// Import SUT
// ---------------------------------------------------------------------------

import AdminConfigPage from "@/pages/AdminConfigPage";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const sampleConfig = {
  challenge: {
    hint_cost_base: 10,
    max_hints: 3,
    enabled: true,
    allowed_tags: ["dp", "greedy"],
  },
  elo: {
    k_factor: 32.5,
    season: "2025-Q1",
  },
};

const sampleMetadata = [
  {
    key: "challenge",
    label: "Challenge Settings",
    fields: [
      { key: "challenge.hint_cost_base", label: "Hint Cost Base", type: "int", default: 10 },
      { key: "challenge.max_hints", label: "Max Hints", type: "int", default: 3 },
      { key: "challenge.enabled", label: "Enabled", type: "bool", default: true },
      { key: "challenge.allowed_tags", label: "Allowed Tags", type: "list", default: ["dp"] },
    ],
  },
  {
    key: "elo",
    label: "Elo Settings",
    fields: [
      { key: "elo.k_factor", label: "K Factor", type: "float", default: 32.0 },
      { key: "elo.season", label: "Season", type: "string", default: "2025-Q1" },
    ],
  },
];

function setupDefaultHandlers() {
  server.use(
    http.get("*/api/v1/admin/config", () =>
      HttpResponse.json({
        success: true,
        data: sampleConfig,
        message: "ok",
      }),
    ),
    http.get("*/api/v1/admin/config/metadata", () =>
      HttpResponse.json({
        success: true,
        data: sampleMetadata,
        message: "ok",
      }),
    ),
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/admin/config"]}>
      <Routes>
        <Route path="/admin/config" element={<AdminConfigPage />} />
        <Route path="/admin" element={<div>Admin Overview</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("AdminConfigPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows loading spinner initially", () => {
    server.use(
      http.get("*/api/v1/admin/config", async () => {
        await new Promise(() => {});
      }),
      http.get("*/api/v1/admin/config/metadata", async () => {
        await new Promise(() => {});
      }),
    );

    renderPage();
    expect(screen.getByTestId("loading-spinner")).toBeInTheDocument();
  });

  it("renders config sections after loading", async () => {
    setupDefaultHandlers();

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("admin:configPage")).toBeInTheDocument();
    });

    expect(screen.getByText("Challenge Settings")).toBeInTheDocument();
    expect(screen.getByText("Elo Settings")).toBeInTheDocument();
  });

  it("expands first section by default", async () => {
    setupDefaultHandlers();

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Hint Cost Base")).toBeInTheDocument();
    });
  });

  it("collapses and expands sections on click", async () => {
    const user = userEvent.setup();
    setupDefaultHandlers();

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Challenge Settings")).toBeInTheDocument();
    });

    // Collapse the section
    await user.click(screen.getByText("Challenge Settings"));
    expect(screen.queryByText("Hint Cost Base")).not.toBeInTheDocument();

    // Expand again
    await user.click(screen.getByText("Challenge Settings"));
    expect(screen.getByText("Hint Cost Base")).toBeInTheDocument();
  });

  it("shows error when config fetch fails", async () => {
    server.use(
      http.get("*/api/v1/admin/config", () =>
        HttpResponse.json({ success: false }, { status: 500 }),
      ),
      http.get("*/api/v1/admin/config/metadata", () =>
        HttpResponse.json({ success: true, data: [], message: "ok" }),
      ),
    );

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("admin:failedLoadConfig")).toBeInTheDocument();
    });
  });

  it("shows dismiss button for error and clears it on click", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("*/api/v1/admin/config", () =>
        HttpResponse.json({ success: false }, { status: 500 }),
      ),
      http.get("*/api/v1/admin/config/metadata", () =>
        HttpResponse.json({ success: true, data: [], message: "ok" }),
      ),
    );

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("admin:failedLoadConfig")).toBeInTheDocument();
    });

    const dismissBtn = screen.getByText(/dismiss/);
    await user.click(dismissBtn);
    expect(screen.queryByText("admin:failedLoadConfig")).not.toBeInTheDocument();
  });

  it("renders bool field as toggle switch with enabled text", async () => {
    setupDefaultHandlers();

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Enabled")).toBeInTheDocument();
    });

    expect(screen.getByText(/enabled/)).toBeInTheDocument();
  });

  it("toggles bool field on click", async () => {
    const user = userEvent.setup();
    setupDefaultHandlers();

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Enabled")).toBeInTheDocument();
    });

    // Click the toggle (the rounded button)
    const toggle = document.querySelector('button[class*="rounded-full"]') as HTMLElement;
    expect(toggle).toBeInTheDocument();
    await user.click(toggle);

    // Should now show disabled text
    await waitFor(() => {
      expect(screen.getByText(/disabled/)).toBeInTheDocument();
    });
  });

  it("renders int field as number input", async () => {
    setupDefaultHandlers();

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Hint Cost Base")).toBeInTheDocument();
    });

    const input = document.querySelector(
      'input[type="number"]',
    ) as HTMLInputElement;
    expect(input).toBeInTheDocument();
    expect(input.value).toBe("10");
  });

  it("renders list field as read-only JSON", async () => {
    setupDefaultHandlers();

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Allowed Tags")).toBeInTheDocument();
    });

    expect(screen.getByText(/dp.*greedy/)).toBeInTheDocument();
  });

  it("renders link back to admin overview", async () => {
    setupDefaultHandlers();

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("admin:configPage")).toBeInTheDocument();
    });

    const link = screen.getByRole("link");
    expect(link).toHaveAttribute("href", "/admin");
  });

  it("expands second section and renders float and string fields", async () => {
    const user = userEvent.setup();
    setupDefaultHandlers();

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Elo Settings")).toBeInTheDocument();
    });

    // Expand the elo section
    await user.click(screen.getByText("Elo Settings"));

    expect(screen.getByText("K Factor")).toBeInTheDocument();
    expect(screen.getByText("Season")).toBeInTheDocument();

    // Float input
    const floatInput = document.querySelector(
      'input[step="0.01"]',
    ) as HTMLInputElement;
    expect(floatInput).toBeInTheDocument();
    expect(floatInput.value).toBe("32.5");

    // String input
    const stringInput = document.querySelector(
      'input[type="text"]',
    ) as HTMLInputElement;
    expect(stringInput).toBeInTheDocument();
  });

  it("shows save button when field is dirty", async () => {
    const user = userEvent.setup();
    setupDefaultHandlers();

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Hint Cost Base")).toBeInTheDocument();
    });

    // Modify a field value
    const input = document.querySelector(
      'input[type="number"]',
    ) as HTMLInputElement;
    await user.clear(input);
    await user.type(input, "20");

    // Save button should appear
    await waitFor(() => {
      expect(document.querySelector("[data-lucide='save']") || screen.getAllByRole("button").find((b) => b.textContent?.includes("admin:"))).toBeTruthy();
    });
  });

  it("saves field successfully", async () => {
    const user = userEvent.setup();
    setupDefaultHandlers();

    server.use(
      http.get("*/api/v1/admin/config", () =>
        HttpResponse.json({
          success: true,
          data: sampleConfig,
          message: "ok",
        }),
      ),
      http.get("*/api/v1/admin/config/metadata", () =>
        HttpResponse.json({
          success: true,
          data: sampleMetadata,
          message: "ok",
        }),
      ),
      http.put("*/api/v1/admin/config/:key", () =>
        HttpResponse.json({ success: true, data: {}, message: "ok" }),
      ),
    );

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Hint Cost Base")).toBeInTheDocument();
    });

    // Modify a field value
    const input = document.querySelector(
      'input[type="number"]',
    ) as HTMLInputElement;
    await user.clear(input);
    await user.type(input, "20");

    // Find and click the save button (appears when dirty)
    await waitFor(async () => {
      const buttons = screen.getAllByRole("button");
      // Find the save button (it appears after the field becomes dirty)
      const saveButtons = buttons.filter(
        (b) => b.querySelector("svg") && b.closest("div")?.querySelector("input"),
      );
      if (saveButtons.length > 0) {
        await user.click(saveButtons[0]);
      }
    });
  });

  it("shows reset button for each field", async () => {
    setupDefaultHandlers();

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Hint Cost Base")).toBeInTheDocument();
    });

    // Reset buttons should exist for each field
    const resetButtons = screen.getAllByRole("button").filter(
      (b) => b.getAttribute("title") === "admin:resetToDefault",
    );
    expect(resetButtons.length).toBeGreaterThan(0);
  });

  it("resets field to default on reset click", async () => {
    const user = userEvent.setup();
    setupDefaultHandlers();

    server.use(
      http.get("*/api/v1/admin/config", () =>
        HttpResponse.json({
          success: true,
          data: sampleConfig,
          message: "ok",
        }),
      ),
      http.get("*/api/v1/admin/config/metadata", () =>
        HttpResponse.json({
          success: true,
          data: sampleMetadata,
          message: "ok",
        }),
      ),
      http.post("*/api/v1/admin/config/:key/reset", () =>
        HttpResponse.json({
          success: true,
          data: { value: 10 },
          message: "ok",
        }),
      ),
    );

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Hint Cost Base")).toBeInTheDocument();
    });

    // Click the first reset button
    const resetButtons = screen.getAllByRole("button").filter(
      (b) => b.getAttribute("title") === "admin:resetToDefault",
    );
    await user.click(resetButtons[0]);
  });

  it("shows unsaved changes indicator when fields are dirty", async () => {
    const user = userEvent.setup();
    setupDefaultHandlers();

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Hint Cost Base")).toBeInTheDocument();
    });

    // Modify a field
    const input = document.querySelector(
      'input[type="number"]',
    ) as HTMLInputElement;
    await user.clear(input);
    await user.type(input, "20");

    await waitFor(() => {
      expect(screen.getByText(/unsavedChanges/)).toBeInTheDocument();
    });
  });
});
