import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: "en" },
  }),
}));

// ---------------------------------------------------------------------------
// Import SUT
// ---------------------------------------------------------------------------

import { ProblemViewer } from "@/components/ProblemViewer";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ProblemViewer", () => {
  const defaultProps = {
    contestId: 1920,
    index: "A",
    blindBox: false,
  };

  // --- Non-blind-box mode (external link card) ---

  it("does not render an iframe", () => {
    const { container } = render(<ProblemViewer {...defaultProps} />);
    expect(container.querySelector("iframe")).toBeNull();
  });

  it("renders problem info text with contestId and index", () => {
    render(<ProblemViewer {...defaultProps} />);
    expect(screen.getByText("Problem 1920A")).toBeInTheDocument();
  });

  it("renders a link to open the problem on Codeforces", () => {
    render(<ProblemViewer {...defaultProps} />);
    const link = screen.getByRole("link", {
      name: /problemViewer.openOnCodeforces/i,
    });
    expect(link).toBeInTheDocument();
    expect(link.getAttribute("href")).toBe(
      "https://codeforces.com/problemset/problem/1920/A",
    );
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toBe("noopener noreferrer");
  });

  it("does not show loading spinner", () => {
    render(<ProblemViewer {...defaultProps} />);
    expect(screen.queryByTestId("loading-spinner")).not.toBeInTheDocument();
  });

  it("does not show iframeNote text", () => {
    render(<ProblemViewer {...defaultProps} />);
    expect(
      screen.queryByText("problemViewer.iframeNote"),
    ).not.toBeInTheDocument();
  });

  // --- Blind-box mode tests ---

  describe("blind-box mode", () => {
    it("does not render an iframe when blindBox is true", () => {
      const { container } = render(
        <ProblemViewer {...defaultProps} blindBox={true} />,
      );
      expect(container.querySelector("iframe")).toBeNull();
    });

    it("renders open-on-codeforces link with correct URL", () => {
      render(<ProblemViewer {...defaultProps} blindBox={true} />);
      const link = screen.getByRole("link", {
        name: /problemViewer.openOnCodeforces/i,
      });
      expect(link).toBeInTheDocument();
      expect(link.getAttribute("href")).toBe(
        "https://codeforces.com/problemset/problem/1920/A",
      );
      expect(link.getAttribute("target")).toBe("_blank");
      expect(link.getAttribute("rel")).toBe("noopener noreferrer");
    });

    it("shows the blind-box description text", () => {
      render(<ProblemViewer {...defaultProps} blindBox={true} />);
      expect(
        screen.getByText("problemViewer.openInNewTab"),
      ).toBeInTheDocument();
    });

    it("does not show loading spinner in blind-box mode", () => {
      render(<ProblemViewer {...defaultProps} blindBox={true} />);
      expect(screen.queryByTestId("loading-spinner")).not.toBeInTheDocument();
    });

    it("does not show problem info in blind-box mode", () => {
      render(<ProblemViewer {...defaultProps} blindBox={true} />);
      expect(screen.queryByText("Problem 1920A")).not.toBeInTheDocument();
    });
  });

  // --- Props variants ---

  it("handles string contestId correctly", () => {
    render(<ProblemViewer {...defaultProps} contestId="1900" />);
    expect(screen.getByText("Problem 1900A")).toBeInTheDocument();
  });

  it("handles sub-problem index like B1", () => {
    render(<ProblemViewer {...defaultProps} index="B1" />);
    expect(screen.getByText("Problem 1920B1")).toBeInTheDocument();
  });

  it("applies custom className to the root container", () => {
    const { container } = render(
      <ProblemViewer {...defaultProps} className="my-custom-class" />,
    );
    const rootDiv = container.firstElementChild as HTMLElement;
    expect(rootDiv.classList.contains("my-custom-class")).toBe(true);
  });
});
