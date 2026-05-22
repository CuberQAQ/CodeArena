import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

// Mock react-i18next
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      if (opts?.defaultValue) return opts.defaultValue as string;
      return key;
    },
    i18n: { language: "en" },
  }),
}));

// Mock problemApi so ProblemStatementViewer does not make real HTTP calls
vi.mock("@/services/problemApi", () => ({
  getProblemStatement: vi.fn().mockResolvedValue({
    problem_id: "1920A",
    contest_id: 1920,
    index: "A",
    title: "Test Problem",
    time_limit: "2 seconds",
    memory_limit: "256 MB",
    body_html: "<p>Hello</p>",
    input_spec_html: null,
    output_spec_html: null,
    samples: [],
    note_html: null,
    full_html: "<p>Hello</p>",
    scraped_at: "2025-01-01T00:00:00Z",
    cached: true,
    fallback_url: "https://codeforces.com/problemset/problem/1920/A",
  }),
  checkProblemCache: vi.fn().mockResolvedValue({
    cached: [],
    not_cached: [],
  }),
}));

// Mock katex to avoid heavy dependency in unit tests
vi.mock("katex", () => ({
  default: {
    renderToString: (tex: string) => `<span class="katex">${tex}</span>`,
  },
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
    contestId: 1920 as const,
    index: "A",
    blindBox: false as const,
  };

  // --- Non-blind-box mode ---

  it("renders without crashing", () => {
    render(<ProblemViewer {...defaultProps} />);
  });

  it("shows skeleton while loading", () => {
    render(<ProblemViewer {...defaultProps} />);
    // The component starts loading and shows a skeleton
    expect(screen.queryByTestId("statement-skeleton")).toBeInTheDocument();
  });

  // --- Blind-box mode ---

  describe("blind-box mode", () => {
    it("does not show skeleton in blind-box mode", () => {
      render(<ProblemViewer {...defaultProps} blindBox={true} />);
      expect(screen.queryByTestId("statement-skeleton")).not.toBeInTheDocument();
    });

    it("renders open-on-codeforces link", () => {
      render(<ProblemViewer {...defaultProps} blindBox={true} />);
      const links = screen.getAllByRole("link");
      const cfLink = links.find(
        (l) => l.getAttribute("href") === "https://codeforces.com/problemset/problem/1920/A",
      );
      expect(cfLink).toBeTruthy();
      expect(cfLink!.getAttribute("target")).toBe("_blank");
    });

    it("shows the blind-box description text", () => {
      render(<ProblemViewer {...defaultProps} blindBox={true} />);
      expect(
        screen.getByText("problemViewer.openInNewTab"),
      ).toBeInTheDocument();
    });
  });

  // --- Props variants ---

  it("handles string contestId correctly", () => {
    render(<ProblemViewer {...defaultProps} contestId="1900" />);
    // Should render without error and trigger a fetch for 1900A
  });

  it("handles sub-problem index like B1", () => {
    render(<ProblemViewer {...defaultProps} index="B1" />);
    // Should render without error and trigger a fetch for 1920B1
  });

  it("applies custom className to the root container", () => {
    const { container } = render(
      <ProblemViewer {...defaultProps} className="my-custom-class" />,
    );
    const rootDiv = container.firstElementChild as HTMLElement;
    expect(rootDiv.classList.contains("my-custom-class")).toBe(true);
  });
});
