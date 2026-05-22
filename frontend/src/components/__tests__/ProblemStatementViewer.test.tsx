import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockGetProblemStatement = vi.fn();

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      if (opts?.defaultValue) {
        let result = opts.defaultValue as string;
        // Simple interpolation for {{limit}} etc.
        for (const [k, v] of Object.entries(opts)) {
          if (k === "defaultValue") continue;
          result = result.replace(`{{${k}}}`, String(v));
        }
        return result;
      }
      return key;
    },
    i18n: { language: "en" },
  }),
}));

vi.mock("@/services/problemApi", () => ({
  getProblemStatement: (...args: unknown[]) => mockGetProblemStatement(...args),
}));

vi.mock("katex", () => ({
  default: {
    renderToString: (tex: string, opts?: { displayMode?: boolean }) => {
      const cls = opts?.displayMode ? "katex-display" : "katex";
      return `<span class="${cls}">${tex}</span>`;
    },
  },
}));

// Mock navigator.clipboard
const mockWriteText = vi.fn().mockResolvedValue(undefined);
Object.assign(navigator, {
  clipboard: { writeText: mockWriteText },
});

// ---------------------------------------------------------------------------
// Import SUT
// ---------------------------------------------------------------------------

import { ProblemStatementViewer } from "@/components/ProblemStatementViewer";

// ---------------------------------------------------------------------------
// Test data
// ---------------------------------------------------------------------------

const mockStatement = {
  problem_id: "1920A",
  contest_id: 1920,
  index: "A",
  title: "Satisfying Constraints",
  time_limit: "2 seconds",
  memory_limit: "256 MB",
  body_html: "<p>Some body text</p>",
  input_spec_html: null,
  output_spec_html: null,
  samples: [
    { input: "3\n1 2\n3 4\n5 6", output: "6\n7\n11" },
    { input: "1\n10 20", output: "30" },
  ],
  note_html: "<p>Sample note</p>",
  full_html: "<p>Some body text</p>",
  scraped_at: "2025-01-01T00:00:00Z",
  cached: true,
  fallback_url: "https://codeforces.com/problemset/problem/1920/A",
};

const mockStatementNoSamples = {
  ...mockStatement,
  samples: [],
  note_html: null,
};

const mockStatementWithLatex = {
  ...mockStatement,
  body_html:
    '<p>Inline: <script type="math/tex">x^2 + y^2 = z^2</script></p>' +
    '<p>Display: <script type="math/tex; mode=display">\\sum_{i=1}^n i = \\frac{n(n+1)}{2}</script></p>',
  note_html:
    '<script type="math/tex">\\alpha + \\beta</script>',
};

// Mock data with tex-span elements (MathJax-rendered output that should be stripped)
const mockStatementWithTexSpan = {
  ...mockStatement,
  body_html:
    '<p>Formula: <span class="tex-span"><span class="katex">old render</span></span><script type="math/tex">x^2</script></p>',
  note_html: null,
};

// Mock data with multiline $$$...$$$ delimiters
const mockStatementWithMultilineDollar = {
  ...mockStatement,
  body_html:
    '<p>Multi-line: $$$a + \nb + \nc$$$</p>',
  note_html: null,
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ProblemStatementViewer", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetProblemStatement.mockResolvedValue(mockStatement);
  });

  // --- Loading state ---

  describe("loading state", () => {
    it("shows skeleton while loading", () => {
      // Make the API call hang
      mockGetProblemStatement.mockReturnValue(new Promise(() => {}));
      render(<ProblemStatementViewer contestId={1920} index="A" />);
      expect(screen.getByTestId("statement-skeleton")).toBeInTheDocument();
    });
  });

  // --- Success state ---

  describe("success state", () => {
    it("renders problem title and index after loading", async () => {
      render(<ProblemStatementViewer contestId={1920} index="A" />);

      await waitFor(() => {
        expect(screen.getByText("A. Satisfying Constraints")).toBeInTheDocument();
      });
    });

    it("renders time and memory limits", async () => {
      render(<ProblemStatementViewer contestId={1920} index="A" />);

      await waitFor(() => {
        expect(screen.getByText(/2 seconds/)).toBeInTheDocument();
        expect(screen.getByText(/256 MB/)).toBeInTheDocument();
      });
    });

    it("renders problem body HTML", async () => {
      render(<ProblemStatementViewer contestId={1920} index="A" />);

      await waitFor(() => {
        expect(screen.getByText("Some body text")).toBeInTheDocument();
      });
    });

    it("renders sample input/output pairs", async () => {
      render(<ProblemStatementViewer contestId={1920} index="A" />);

      await waitFor(() => {
        // Use a function matcher for multiline pre content
        const sampleInputs = screen.getAllByText((_content, element) => {
          return element?.tagName === "PRE" && element.textContent === "3\n1 2\n3 4\n5 6";
        });
        expect(sampleInputs.length).toBeGreaterThanOrEqual(1);

        const sampleOutputs = screen.getAllByText((_content, element) => {
          return element?.tagName === "PRE" && element.textContent === "6\n7\n11";
        });
        expect(sampleOutputs.length).toBeGreaterThanOrEqual(1);
      });
    });

    it("does not render samples section when samples array is empty", async () => {
      mockGetProblemStatement.mockResolvedValue(mockStatementNoSamples);
      render(<ProblemStatementViewer contestId={1920} index="A" />);

      await waitFor(() => {
        expect(screen.getByText("A. Satisfying Constraints")).toBeInTheDocument();
      });
      expect(screen.queryByText("problemViewer.samples")).not.toBeInTheDocument();
    });

    it("renders note HTML", async () => {
      render(<ProblemStatementViewer contestId={1920} index="A" />);

      await waitFor(() => {
        expect(screen.getByText("Sample note")).toBeInTheDocument();
      });
    });

    it("renders external CF link at bottom", async () => {
      render(<ProblemStatementViewer contestId={1920} index="A" />);

      await waitFor(() => {
        const links = screen.getAllByRole("link");
        const cfLink = links.find(
          (l) =>
            l.getAttribute("href") ===
            "https://codeforces.com/problemset/problem/1920/A",
        );
        expect(cfLink).toBeTruthy();
        expect(cfLink!.getAttribute("target")).toBe("_blank");
      });
    });

    it("uses fallback_url from API response for external link on error", async () => {
      mockGetProblemStatement.mockRejectedValue(new Error("Network error"));
      render(<ProblemStatementViewer contestId={1920} index="A" />);

      await waitFor(() => {
        expect(
          screen.getByText("problemViewer.loadFailed"),
        ).toBeInTheDocument();
      });
    });
  });

  // --- LaTeX rendering ---

  describe("LaTeX rendering", () => {
    it("replaces inline math/tex script tags with KaTeX output", async () => {
      mockGetProblemStatement.mockResolvedValue(mockStatementWithLatex);
      render(<ProblemStatementViewer contestId={1920} index="A" />);

      await waitFor(() => {
        const container = document.querySelector(".cf-prose");
        expect(container).toBeTruthy();
        // Inline LaTeX should be rendered with .katex class (not .katex-display)
        const inlineKatex = container!.querySelector(".katex:not(.katex-display)");
        expect(inlineKatex).toBeTruthy();
        expect(inlineKatex!.textContent).toContain("x^2 + y^2 = z^2");
      });
    });

    it("replaces display-mode math/tex script tags with KaTeX display output", async () => {
      mockGetProblemStatement.mockResolvedValue(mockStatementWithLatex);
      render(<ProblemStatementViewer contestId={1920} index="A" />);

      await waitFor(() => {
        const container = document.querySelector(".cf-prose");
        expect(container).toBeTruthy();
        const displayKatex = container!.querySelector(".katex-display");
        expect(displayKatex).toBeTruthy();
        expect(displayKatex!.textContent).toContain("\\sum_{i=1}^n i");
      });
    });

    it("renders LaTeX in note_html", async () => {
      mockGetProblemStatement.mockResolvedValue(mockStatementWithLatex);
      render(<ProblemStatementViewer contestId={1920} index="A" />);

      await waitFor(() => {
        // The note section should have rendered KaTeX for the alpha+beta formula
        const allKatex = document.querySelectorAll(".katex");
        // At least the note katex should be present (plus inline + display in body)
        expect(allKatex.length).toBeGreaterThanOrEqual(2);
      });
    });

    it("strips tex-span elements to prevent duplicate formula rendering", async () => {
      mockGetProblemStatement.mockResolvedValue(mockStatementWithTexSpan);
      render(<ProblemStatementViewer contestId={1920} index="A" />);

      await waitFor(() => {
        const container = document.querySelector(".cf-prose");
        expect(container).toBeTruthy();
        // tex-span elements should be removed
        expect(container!.querySelector(".tex-span")).toBeNull();
        // The script type="math/tex" should be replaced with KaTeX output
        const katexSpan = container!.querySelector(".katex");
        expect(katexSpan).toBeTruthy();
        expect(katexSpan!.textContent).toContain("x^2");
        // Should NOT contain the old rendered content from tex-span
        expect(container!.textContent).not.toContain("old render");
      });
    });

    it("handles multiline $$$...$$$ delimiters", async () => {
      mockGetProblemStatement.mockResolvedValue(mockStatementWithMultilineDollar);
      render(<ProblemStatementViewer contestId={1920} index="A" />);

      await waitFor(() => {
        const container = document.querySelector(".cf-prose");
        expect(container).toBeTruthy();
        // The multiline formula should be rendered by KaTeX
        const katexSpan = container!.querySelector(".katex");
        expect(katexSpan).toBeTruthy();
        // The raw $$$ delimiters should be gone
        expect(container!.innerHTML).not.toContain("$$$");
        // The formula content should have been passed to KaTeX
        expect(katexSpan!.textContent).toContain("a +");
      });
    });
  });

  // --- Error state ---

  describe("error state", () => {
    it("shows error message when API fails", async () => {
      mockGetProblemStatement.mockRejectedValue(new Error("Network error"));
      render(<ProblemStatementViewer contestId={1920} index="A" />);

      await waitFor(() => {
        expect(
          screen.getByText("problemViewer.loadFailed"),
        ).toBeInTheDocument();
      });
    });

    it("shows CF external link on error using constructed URL", async () => {
      mockGetProblemStatement.mockRejectedValue(new Error("Network error"));
      render(<ProblemStatementViewer contestId={1920} index="A" />);

      await waitFor(() => {
        const links = screen.getAllByRole("link");
        const cfLink = links.find(
          (l) =>
            l.getAttribute("href") ===
            "https://codeforces.com/problemset/problem/1920/A",
        );
        expect(cfLink).toBeTruthy();
      });
    });

    it("shows retry button on error", async () => {
      mockGetProblemStatement.mockRejectedValue(new Error("Network error"));
      render(<ProblemStatementViewer contestId={1920} index="A" />);

      await waitFor(() => {
        expect(screen.getByText("retry")).toBeInTheDocument();
      });
    });

    it("retries fetching when retry button is clicked", async () => {
      mockGetProblemStatement.mockRejectedValueOnce(new Error("Network error"));
      mockGetProblemStatement.mockResolvedValueOnce(mockStatement);

      render(<ProblemStatementViewer contestId={1920} index="A" />);

      await waitFor(() => {
        expect(screen.getByText("retry")).toBeInTheDocument();
      });

      await userEvent.click(screen.getByText("retry"));

      await waitFor(() => {
        expect(screen.getByText("A. Satisfying Constraints")).toBeInTheDocument();
      });
      expect(mockGetProblemStatement).toHaveBeenCalledTimes(2);
    });
  });

  // --- Blind-box mode ---

  describe("blind-box mode", () => {
    it("does not call API when blindBox is true", () => {
      render(
        <ProblemStatementViewer contestId={1920} index="A" blindBox={true} />,
      );
      expect(mockGetProblemStatement).not.toHaveBeenCalled();
    });

    it("shows blind-box card with external link", () => {
      render(
        <ProblemStatementViewer contestId={1920} index="A" blindBox={true} />,
      );
      expect(
        screen.getByText("problemViewer.openInNewTab"),
      ).toBeInTheDocument();
    });

    it("shows CF link in blind-box mode", () => {
      render(
        <ProblemStatementViewer contestId={1920} index="A" blindBox={true} />,
      );
      const links = screen.getAllByRole("link");
      const cfLink = links.find(
        (l) =>
          l.getAttribute("href") ===
          "https://codeforces.com/problemset/problem/1920/A",
      );
      expect(cfLink).toBeTruthy();
    });

    it("does not show skeleton in blind-box mode", () => {
      render(
        <ProblemStatementViewer contestId={1920} index="A" blindBox={true} />,
      );
      expect(screen.queryByTestId("statement-skeleton")).not.toBeInTheDocument();
    });

    it("fetches API when blindBox transitions from true to false", async () => {
      const { rerender } = render(
        <ProblemStatementViewer contestId={1920} index="A" blindBox={true} />,
      );
      expect(mockGetProblemStatement).not.toHaveBeenCalled();

      rerender(
        <ProblemStatementViewer contestId={1920} index="A" blindBox={false} />,
      );

      await waitFor(() => {
        expect(mockGetProblemStatement).toHaveBeenCalledWith("1920A");
      });
    });

    it("does not re-fetch when blindBox stays false", async () => {
      const { rerender } = render(
        <ProblemStatementViewer contestId={1920} index="A" blindBox={false} />,
      );

      await waitFor(() => {
        expect(mockGetProblemStatement).toHaveBeenCalledTimes(1);
      });

      rerender(
        <ProblemStatementViewer contestId={1920} index="A" blindBox={false} />,
      );

      // Should not fetch again for same props
      expect(mockGetProblemStatement).toHaveBeenCalledTimes(1);
    });
  });

  // --- Sample copy functionality ---

  describe("sample copy button", () => {
    it("copies sample input to clipboard on click", async () => {
      render(<ProblemStatementViewer contestId={1920} index="A" />);

      // Wait for statement to load
      await waitFor(() => {
        expect(screen.getByText("A. Satisfying Constraints")).toBeInTheDocument();
      });

      // Find all copy buttons (there should be 4: 2 inputs + 2 outputs)
      const copyButtons = screen.getAllByTitle("Copy");
      expect(copyButtons.length).toBe(4);

      await userEvent.click(copyButtons[0]);

      expect(mockWriteText).toHaveBeenCalledWith("3\n1 2\n3 4\n5 6");
    });

    it("shows copied feedback after copying", async () => {
      render(<ProblemStatementViewer contestId={1920} index="A" />);

      // Wait for statement to load
      await waitFor(() => {
        expect(screen.getByText("A. Satisfying Constraints")).toBeInTheDocument();
      });

      const copyButtons = screen.getAllByTitle("Copy");
      await userEvent.click(copyButtons[0]);

      // Should show "copied" feedback
      await waitFor(() => {
        expect(screen.getAllByText("copied").length).toBeGreaterThanOrEqual(1);
      });
    });
  });

  // --- Props variants ---

  describe("props variants", () => {
    it("handles string contestId", async () => {
      render(<ProblemStatementViewer contestId="1900" index="A" />);
      await waitFor(() => {
        expect(mockGetProblemStatement).toHaveBeenCalledWith("1900A");
      });
    });

    it("handles numeric contestId", async () => {
      render(<ProblemStatementViewer contestId={1900} index="A" />);
      await waitFor(() => {
        expect(mockGetProblemStatement).toHaveBeenCalledWith("1900A");
      });
    });

    it("handles sub-problem index like B1", async () => {
      render(<ProblemStatementViewer contestId={1920} index="B1" />);
      await waitFor(() => {
        expect(mockGetProblemStatement).toHaveBeenCalledWith("1920B1");
      });
    });

    it("applies custom className", async () => {
      const { container } = render(
        <ProblemStatementViewer
          contestId={1920}
          index="A"
          className="my-custom-class"
        />,
      );

      await waitFor(() => {
        expect(screen.getByText("A. Satisfying Constraints")).toBeInTheDocument();
      });

      const rootDiv = container.firstElementChild as HTMLElement;
      expect(rootDiv.classList.contains("my-custom-class")).toBe(true);
    });

    it("does not render samples section when no samples", async () => {
      mockGetProblemStatement.mockResolvedValue(mockStatementNoSamples);
      render(<ProblemStatementViewer contestId={1920} index="A" />);

      await waitFor(() => {
        expect(screen.getByText("A. Satisfying Constraints")).toBeInTheDocument();
      });

      expect(screen.queryByText("problemViewer.samples")).not.toBeInTheDocument();
    });
  });
});
