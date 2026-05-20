import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";

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
    <div data-testid="loading-spinner">{text ?? "loading"}</div>
  ),
}));

vi.mock("@/components/ui/button", () => ({
  Button: ({
    children,
    ...props
  }: {
    children: React.ReactNode;
    [key: string]: unknown;
  }) => <button {...props}>{children}</button>,
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

  // --- Non-blind-box (iframe) mode ---

  it("renders an iframe with the correct CF URL", () => {
    const { container } = render(<ProblemViewer {...defaultProps} />);
    const iframe = container.querySelector("iframe");
    expect(iframe).not.toBeNull();
    expect(iframe?.getAttribute("src")).toBe(
      "https://codeforces.com/problemset/problem/1920/A",
    );
  });

  it("shows loading spinner while iframe is loading", () => {
    render(<ProblemViewer {...defaultProps} />);
    expect(screen.getByTestId("loading-spinner")).toBeInTheDocument();
    expect(screen.getByText("problemViewer.loadingProblem")).toBeInTheDocument();
  });

  it("hides loading spinner after iframe loads", async () => {
    const { container } = render(<ProblemViewer {...defaultProps} />);
    const iframe = container.querySelector("iframe");

    // Simulate iframe load event via fireEvent to trigger React's handler
    if (iframe) fireEvent.load(iframe);

    await waitFor(() => {
      expect(screen.queryByTestId("loading-spinner")).not.toBeInTheDocument();
    });
  });

  it("always shows the fallback note and link below the iframe", () => {
    render(<ProblemViewer {...defaultProps} />);
    expect(screen.getByText("problemViewer.iframeNote")).toBeInTheDocument();

    // There should be a link with the openOnCodeforces text
    const links = screen.getAllByText("problemViewer.openOnCodeforces");
    // At least the fallback link below the iframe
    expect(links.length).toBeGreaterThanOrEqual(1);
  });

  it("fallback link points to the correct CF URL and opens in new tab", () => {
    render(<ProblemViewer {...defaultProps} />);
    const fallbackLink = screen
      .getAllByRole("link")
      .find((link) => link.textContent?.includes("openOnCodeforces"));
    expect(fallbackLink).toBeDefined();
    expect(fallbackLink?.getAttribute("href")).toBe(
      "https://codeforces.com/problemset/problem/1920/A",
    );
    expect(fallbackLink?.getAttribute("target")).toBe("_blank");
    expect(fallbackLink?.getAttribute("rel")).toBe("noopener noreferrer");
  });

  it("sets proper sandbox attribute on iframe", () => {
    const { container } = render(<ProblemViewer {...defaultProps} />);
    const iframe = container.querySelector("iframe");
    expect(iframe?.getAttribute("sandbox")).toBe(
      "allow-scripts allow-same-origin",
    );
  });

  it("has lazy loading on iframe", () => {
    const { container } = render(<ProblemViewer {...defaultProps} />);
    const iframe = container.querySelector("iframe");
    expect(iframe?.getAttribute("loading")).toBe("lazy");
  });

  // --- Blind-box mode tests ---

  describe("blind-box mode", () => {
    it("does not render an iframe when blindBox is true", () => {
      const { container } = render(
        <ProblemViewer {...defaultProps} blindBox={true} />,
      );
      expect(container.querySelector("iframe")).toBeNull();
    });

    it("renders open-in-new-tab link with correct URL", () => {
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

    it("does not show iframe fallback note in blind-box mode", () => {
      render(<ProblemViewer {...defaultProps} blindBox={true} />);
      expect(
        screen.queryByText("problemViewer.iframeNote"),
      ).not.toBeInTheDocument();
    });
  });

  // --- Props variants ---

  it("handles string contestId correctly", () => {
    const { container } = render(
      <ProblemViewer {...defaultProps} contestId="1900" />,
    );
    const iframe = container.querySelector("iframe");
    expect(iframe?.getAttribute("src")).toBe(
      "https://codeforces.com/problemset/problem/1900/A",
    );
  });

  it("handles sub-problem index like B1", () => {
    const { container } = render(
      <ProblemViewer {...defaultProps} index="B1" />,
    );
    const iframe = container.querySelector("iframe");
    expect(iframe?.getAttribute("src")).toBe(
      "https://codeforces.com/problemset/problem/1920/B1",
    );
  });

  it("applies custom className to the root container", () => {
    const { container } = render(
      <ProblemViewer {...defaultProps} className="my-custom-class" />,
    );
    const rootDiv = container.firstElementChild as HTMLElement;
    expect(rootDiv.classList.contains("my-custom-class")).toBe(true);
  });
});
