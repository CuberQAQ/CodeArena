import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

// Mock react-i18next
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => {
      const map: Record<string, string> = {
        "installBanner.title": "Install Code Arena",
        "installBanner.description": "Install Code Arena to your desktop for a better experience",
        "installBanner.install": "Install",
        "installBanner.dismiss": "Not now",
      };
      return map[key] ?? key;
    },
    i18n: { language: "en" },
  }),
}));

// Mock the useInstallPrompt hook so we can control its return value per-test.
const mockPromptInstall = vi.fn().mockResolvedValue(true);
const mockDismiss = vi.fn();

let mockCanInstall = false;
let mockIsInstalled = false;

vi.mock("@/hooks/useInstallPrompt", () => ({
  useInstallPrompt: () => ({
    canInstall: mockCanInstall,
    isInstalled: mockIsInstalled,
    promptInstall: mockPromptInstall,
    dismiss: mockDismiss,
  }),
}));

// ---------------------------------------------------------------------------
// Import SUT (after mocks)
// ---------------------------------------------------------------------------

import { InstallBanner } from "@/components/InstallBanner";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("InstallBanner", () => {
  beforeEach(() => {
    mockCanInstall = false;
    mockIsInstalled = false;
    mockPromptInstall.mockResolvedValue(true);
    mockPromptInstall.mockClear();
    mockDismiss.mockClear();
  });

  it("renders nothing when canInstall is false", () => {
    mockCanInstall = false;
    const { container } = render(<InstallBanner />);
    expect(container.innerHTML).toBe("");
  });

  it("renders the banner when canInstall is true", () => {
    mockCanInstall = true;
    render(<InstallBanner />);
    expect(screen.getByText("Install Code Arena")).toBeInTheDocument();
  });

  it("renders the description text", () => {
    mockCanInstall = true;
    render(<InstallBanner />);
    expect(
      screen.getByText(/Install Code Arena to your desktop/),
    ).toBeInTheDocument();
  });

  it("renders the install button with correct label", () => {
    mockCanInstall = true;
    render(<InstallBanner />);
    // The button text is "Install" (from the Download icon + text)
    expect(screen.getByText("Install")).toBeInTheDocument();
  });

  it("calls promptInstall when install button is clicked", () => {
    mockCanInstall = true;
    render(<InstallBanner />);
    // Find the button containing the install text
    const buttons = screen.getAllByRole("button");
    const installBtn = buttons.find((btn) => btn.textContent?.includes("Install"));
    expect(installBtn).toBeDefined();
    fireEvent.click(installBtn!);
    expect(mockPromptInstall).toHaveBeenCalledTimes(1);
  });

  it("calls dismiss when close button is clicked", () => {
    mockCanInstall = true;
    render(<InstallBanner />);
    // The dismiss button has aria-label="Not now"
    const dismissBtn = screen.getByLabelText("Not now");
    fireEvent.click(dismissBtn);
    expect(mockDismiss).toHaveBeenCalledTimes(1);
  });

  it("has correct styling classes for light/dark mode", () => {
    mockCanInstall = true;
    const { container } = render(<InstallBanner />);
    const banner = container.querySelector(".bg-purple-50");
    expect(banner).toBeInTheDocument();
    // Dark mode class
    expect(banner?.className).toContain("dark:bg-purple-900/20");
  });
});
