import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockChangeLanguage = vi.fn();

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: "en", changeLanguage: mockChangeLanguage },
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
});
