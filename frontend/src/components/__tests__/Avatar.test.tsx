import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: "en" },
  }),
}));

const mockPost = vi.fn();

vi.mock("@/services/api", () => ({
  default: {
    post: (...args: unknown[]) => mockPost(...args),
  },
}));

// ---------------------------------------------------------------------------
// Import SUT
// ---------------------------------------------------------------------------

import { Avatar, AvatarUpload } from "@/components/Avatar";

// ---------------------------------------------------------------------------
// Tests -- Avatar display
// ---------------------------------------------------------------------------

describe("Avatar (display)", () => {
  it("renders user icon placeholder when no userId or src", () => {
    const { container } = render(<Avatar />);
    // Should show User icon placeholder (div with bg-muted)
    const img = container.querySelector("img");
    expect(img).toBeNull();
  });

  it("renders image when userId is provided", () => {
    const { container } = render(<Avatar userId="user-1" />);
    const img = container.querySelector("img") as HTMLImageElement;
    expect(img).toBeInTheDocument();
    expect(img.getAttribute("src")).toBe("/api/v1/auth/avatar/user-1");
  });

  it("uses custom size", () => {
    const { container } = render(<Avatar size={80} />);
    const root = container.firstElementChild as HTMLElement;
    expect(root.style.width).toBe("80px");
    expect(root.style.height).toBe("80px");
  });

  it("shows placeholder on image error", () => {
    const { container } = render(<Avatar userId="user-1" />);
    const img = container.querySelector("img") as HTMLImageElement;
    fireEvent.error(img);
    // After error, img should be replaced with placeholder
    expect(container.querySelector("img")).toBeNull();
  });

  it("applies custom className", () => {
    const { container } = render(<Avatar className="test-class" />);
    const root = container.firstElementChild as HTMLElement;
    expect(root.classList.contains("test-class")).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Tests -- AvatarUpload
// ---------------------------------------------------------------------------

describe("AvatarUpload", () => {
  it("renders the upload button", () => {
    render(<AvatarUpload userId="user-1" />);
    const button = screen.getByRole("button");
    expect(button).toBeInTheDocument();
    expect(button).toHaveAttribute("title", "avatar.clickToUpload");
  });

  it("renders with custom size", () => {
    render(<AvatarUpload userId="user-1" size={120} />);
    const button = screen.getByRole("button");
    expect(button.style.width).toBe("120px");
    expect(button.style.height).toBe("120px");
  });

  it("shows error for invalid file type", async () => {
    render(<AvatarUpload userId="user-1" />);

    const input = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;

    const file = new File(["test"], "test.gif", { type: "image/gif" });
    Object.defineProperty(input, "files", { value: [file] });

    fireEvent.change(input);

    expect(screen.getByText("avatar.invalidFormat")).toBeInTheDocument();
  });

  it("shows error for file too large (>2MB)", async () => {
    render(<AvatarUpload userId="user-1" />);

    const input = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;

    const bigFile = new File(["x".repeat(3 * 1024 * 1024)], "big.jpg", {
      type: "image/jpeg",
    });
    Object.defineProperty(input, "files", { value: [bigFile] });

    fireEvent.change(input);

    expect(screen.getByText("avatar.fileTooLarge")).toBeInTheDocument();
  });
});
