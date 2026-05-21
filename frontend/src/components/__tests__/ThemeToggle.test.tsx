import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ThemeToggle } from "@/components/ThemeToggle";

// Mock react-i18next
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => {
      const map: Record<string, string> = {
        "theme.light": "Light",
        "theme.dark": "Dark",
        "theme.system": "System",
      };
      return map[key] ?? key;
    },
    i18n: { language: "en" },
  }),
}));

// Mock matchMedia for jsdom
beforeEach(() => {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
  localStorage.clear();
  document.documentElement.classList.remove("dark");
});

afterEach(() => {
  localStorage.clear();
  document.documentElement.classList.remove("dark");
});

describe("ThemeToggle", () => {
  it("renders with system theme by default", () => {
    render(<ThemeToggle />);
    expect(screen.getByLabelText("System")).toBeInTheDocument();
  });

  it("displays theme label text", () => {
    render(<ThemeToggle />);
    expect(screen.getByText("System")).toBeInTheDocument();
  });

  it("cycles from system to light on click", async () => {
    localStorage.setItem("theme", "system");
    render(<ThemeToggle />);
    const button = screen.getByRole("button");
    await userEvent.click(button);
    expect(localStorage.getItem("theme")).toBe("light");
  });

  it("cycles from light to dark on click", async () => {
    localStorage.setItem("theme", "light");
    render(<ThemeToggle />);
    const button = screen.getByRole("button");
    await userEvent.click(button);
    expect(localStorage.getItem("theme")).toBe("dark");
  });

  it("applies dark class to document element when theme is dark", async () => {
    localStorage.setItem("theme", "light");
    render(<ThemeToggle />);
    const button = screen.getByRole("button");
    // light -> dark
    await userEvent.click(button);
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("removes dark class when theme is light", async () => {
    localStorage.setItem("theme", "dark");
    document.documentElement.classList.add("dark");
    render(<ThemeToggle />);
    const button = screen.getByRole("button");
    // dark -> system (system defaults to light in test env)
    await userEvent.click(button);
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });

  it("updates label text after cycling", async () => {
    localStorage.setItem("theme", "system");
    render(<ThemeToggle />);
    const button = screen.getByRole("button");
    // system -> light
    await userEvent.click(button);
    expect(screen.getByText("Light")).toBeInTheDocument();
  });
});
