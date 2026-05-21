import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, params?: Record<string, unknown>) => {
      if (params) {
        return Object.entries(params).reduce(
          (acc, [k, v]) => acc.replace(`{{${k}}}`, String(v)),
          key,
        );
      }
      return key;
    },
    i18n: { language: "en" },
  }),
}));

vi.mock("framer-motion", () => ({
  motion: {
    div: ({ children, ...props }: React.PropsWithChildren<Record<string, unknown>>) => (
      <div {...props}>{children}</div>
    ),
    p: ({ children, ...props }: React.PropsWithChildren<Record<string, unknown>>) => (
      <p {...props}>{children}</p>
    ),
  },
  AnimatePresence: ({ children }: React.PropsWithChildren) => <>{children}</>,
}));

vi.mock("@/components/LoadingSpinner", () => ({
  LoadingSpinner: ({ text }: { text?: string }) => (
    <div data-testid="loading-spinner">{text ?? "Loading..."}</div>
  ),
}));

vi.mock("@/utils", () => ({
  getRatingColor: () => "#000000",
}));

const mockNavigate = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

const mockFreePlaySearch = vi.fn();
const mockFreePlayRecommend = vi.fn();
const mockFreePlayStart = vi.fn();

vi.mock("@/services/freePlayApi", () => ({
  freePlaySearch: (...args: unknown[]) => mockFreePlaySearch(...args),
  freePlayRecommend: () => mockFreePlayRecommend(),
  freePlayStart: (...args: unknown[]) => mockFreePlayStart(...args),
}));

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

import FreePlayPage from "../FreePlayPage";

function renderPage() {
  return render(
    <MemoryRouter>
      <FreePlayPage />
    </MemoryRouter>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("FreePlayPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // 1. Renders header and tabs
  it("renders title, description, and tab buttons", () => {
    renderPage();
    expect(screen.getByText("title")).toBeInTheDocument();
    expect(screen.getByText("description")).toBeInTheDocument();
    expect(screen.getByText("tabs.manual")).toBeInTheDocument();
    expect(screen.getByText("tabs.recommend")).toBeInTheDocument();
  });

  // 2. Manual tab is active by default
  it("shows manual filter panel by default", () => {
    renderPage();
    expect(screen.getByText("ratingRange")).toBeInTheDocument();
    expect(screen.getByText("searchProblems")).toBeInTheDocument();
  });

  // 3. Switch to recommend tab
  it("switches to recommend tab on click", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByText("tabs.recommend"));
    expect(screen.getByText("recommendProblem")).toBeInTheDocument();
  });

  // 4. Tag selection toggles
  it("toggles tag chips on click", async () => {
    const user = userEvent.setup();
    renderPage();

    const dpTag = screen.getByText("dp");
    expect(dpTag).toBeInTheDocument();
    await user.click(dpTag);
    // Tag should still be in the document (now selected)
    expect(screen.getByText("dp")).toBeInTheDocument();
  });

  // 5. Manual search - problem found
  it("shows problem card after successful search", async () => {
    mockFreePlaySearch.mockResolvedValue({
      found: true,
      problem: {
        name: "Two Sum",
        contest_id: "1",
        index: "A",
        rating: 1200,
        tags: ["dp"],
        url: "https://codeforces.com/1/A",
      },
    });
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByText("searchProblems"));

    await waitFor(() => {
      expect(screen.getByText("Two Sum")).toBeInTheDocument();
    });
    expect(screen.getAllByText("1200").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("dp").length).toBeGreaterThanOrEqual(1);
  });

  // 6. Manual search - no problem found
  it("shows error when no problem found", async () => {
    mockFreePlaySearch.mockResolvedValue({
      found: false,
      message: "No problem found for given criteria",
    });
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByText("searchProblems"));

    await waitFor(() => {
      expect(screen.getByText("No problem found for given criteria")).toBeInTheDocument();
    });
  });

  // 7. Manual search failure
  it("shows error when search throws exception", async () => {
    mockFreePlaySearch.mockRejectedValue(new Error("Network error"));
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByText("searchProblems"));

    await waitFor(() => {
      expect(screen.getByText("error.searchFailed")).toBeInTheDocument();
    });
  });

  // 8. Recommend - problem found
  it("shows problem card after successful recommendation", async () => {
    mockFreePlayRecommend.mockResolvedValue({
      found: true,
      problem: {
        name: "Binary Search",
        contest_id: "2",
        index: "B",
        rating: 1500,
        tags: ["binary search"],
        url: "https://codeforces.com/2/B",
      },
      recommended_tag: "binary search",
    });
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByText("tabs.recommend"));
    await user.click(screen.getByText("recommendProblem"));

    await waitFor(() => {
      expect(screen.getByText("Binary Search")).toBeInTheDocument();
    });
    expect(screen.getByText("recommendReason")).toBeInTheDocument();
  });

  // 9. Recommend failure
  it("shows error when recommendation fails", async () => {
    mockFreePlayRecommend.mockRejectedValue(new Error("Network error"));
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByText("tabs.recommend"));
    await user.click(screen.getByText("recommendProblem"));

    await waitFor(() => {
      expect(screen.getByText("error.recommendFailed")).toBeInTheDocument();
    });
  });

  // 10. Start session after finding problem
  it("starts a session and navigates to session page", async () => {
    const problem = {
      name: "Two Sum",
      contest_id: "1",
      index: "A",
      rating: 1200,
      tags: ["dp"],
      url: "https://codeforces.com/1/A",
    };
    mockFreePlaySearch.mockResolvedValue({ found: true, problem });
    mockFreePlayStart.mockResolvedValue({ session_id: "sess1" });
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByText("searchProblems"));

    await waitFor(() => {
      expect(screen.getByText("free_play:startProblem")).toBeInTheDocument();
    });

    await user.click(screen.getByText("free_play:startProblem"));

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith(
        "/free-play/session/sess1",
        expect.objectContaining({ state: { problem } }),
      );
    });
  });

  // 11. Start session failure
  it("shows error when starting session fails", async () => {
    const problem = {
      name: "Two Sum",
      contest_id: "1",
      index: "A",
      rating: 1200,
      tags: ["dp"],
      url: "https://codeforces.com/1/A",
    };
    mockFreePlaySearch.mockResolvedValue({ found: true, problem });
    mockFreePlayStart.mockRejectedValue(new Error("Start failed"));
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByText("searchProblems"));

    await waitFor(() => {
      expect(screen.getByText("free_play:startProblem")).toBeInTheDocument();
    });

    await user.click(screen.getByText("free_play:startProblem"));

    await waitFor(() => {
      expect(screen.getByText("error.startFailed")).toBeInTheDocument();
    });
  });

  // 12. More tags dialog opens
  it("opens more tags dialog on click", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByText("moreTags"));
    expect(screen.getByText("moreTagsTitle")).toBeInTheDocument();
  });
});
