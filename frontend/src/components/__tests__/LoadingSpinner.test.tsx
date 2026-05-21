import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Import SUT
// ---------------------------------------------------------------------------

import { LoadingSpinner } from "@/components/LoadingSpinner";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("LoadingSpinner", () => {
  it("renders with default size (md)", () => {
    const { container } = render(<LoadingSpinner />);
    const svg = container.querySelector("svg");
    expect(svg).toBeInTheDocument();
  });

  it("renders with text when provided", () => {
    render(<LoadingSpinner text="Loading data..." />);
    expect(screen.getByText("Loading data...")).toBeInTheDocument();
  });

  it("does not render text paragraph when text is not provided", () => {
    const { container } = render(<LoadingSpinner />);
    const p = container.querySelector("p");
    expect(p).toBeNull();
  });

  it("renders with sm size", () => {
    const { container } = render(<LoadingSpinner size="sm" />);
    const svg = container.querySelector("svg");
    expect(svg?.classList.contains("size-4")).toBe(true);
  });

  it("renders with lg size", () => {
    const { container } = render(<LoadingSpinner size="lg" />);
    const svg = container.querySelector("svg");
    expect(svg?.classList.contains("size-8")).toBe(true);
  });

  it("applies custom className", () => {
    const { container } = render(
      <LoadingSpinner className="my-custom-class" />,
    );
    const root = container.firstElementChild as HTMLElement;
    expect(root.classList.contains("my-custom-class")).toBe(true);
  });
});
