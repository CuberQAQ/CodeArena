import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockChangeLanguage = vi.fn();
let mockLanguage = "en";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: {
      get language() { return mockLanguage; },
      changeLanguage: mockChangeLanguage,
    },
  }),
}));

// ---------------------------------------------------------------------------
// Import SUT
// ---------------------------------------------------------------------------

import { LanguageSwitcher } from "@/components/LanguageSwitcher";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("LanguageSwitcher", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockLanguage = "en";
  });

  it("renders the button with text", () => {
    render(<LanguageSwitcher />);
    expect(screen.getByRole("button", { name: /EN/i })).toBeInTheDocument();
  });

  it("calls changeLanguage with 'zh' when current language is 'en'", async () => {
    const user = userEvent.setup();
    render(<LanguageSwitcher />);
    await user.click(screen.getByRole("button"));
    expect(mockChangeLanguage).toHaveBeenCalledWith("zh");
  });

  it("shows English title tooltip when language is en", () => {
    render(<LanguageSwitcher />);
    expect(screen.getByRole("button")).toHaveAttribute("title", "Switch to Chinese");
  });

  it("calls changeLanguage with 'en' when current language is 'zh'", async () => {
    mockLanguage = "zh";
    const user = userEvent.setup();
    render(<LanguageSwitcher />);
    await user.click(screen.getByRole("button"));
    expect(mockChangeLanguage).toHaveBeenCalledWith("en");
  });

  it("shows Chinese title tooltip when language is zh", () => {
    mockLanguage = "zh";
    render(<LanguageSwitcher />);
    expect(screen.getByRole("button")).toHaveAttribute("title", "切换到英文");
  });
});
