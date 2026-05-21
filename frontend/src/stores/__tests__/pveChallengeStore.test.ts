import { describe, it, expect, vi, beforeEach } from "vitest";
import { usePvEChallengeStore } from "../pveChallengeStore";
import type {
  PvEStartResponse,
  PvEDetailResponse,
  PvESubmitResultResponse,
  PvEQuitResponse,
  PvEHistoryResponse,
} from "@/types";

// ---------------------------------------------------------------------------
// Mock the pveChallengeApi module
// ---------------------------------------------------------------------------

const mockStartChallenge = vi.fn();
const mockGetChallenge = vi.fn();
const mockSubmitResult = vi.fn();
const mockQuitChallenge = vi.fn();
const mockGetHistory = vi.fn();

vi.mock("@/services/pveChallengeApi", () => ({
  startChallenge: (...args: unknown[]) => mockStartChallenge(...args),
  getChallenge: (...args: unknown[]) => mockGetChallenge(...args),
  submitResult: (...args: unknown[]) => mockSubmitResult(...args),
  quitChallenge: (...args: unknown[]) => mockQuitChallenge(...args),
  getHistory: (...args: unknown[]) => mockGetHistory(...args),
}));

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const fakeStartResponse: PvEStartResponse = {
  session_id: "pve-session-1",
};

const fakeDetailResponse: PvEDetailResponse = {
  session_id: "pve-session-1",
  status: "in_progress",
  problem_title: "Test Problem",
  problem_description: "Solve this problem",
  started_at: "2025-01-01T00:00:00Z",
  time_limit: 1800,
  difficulty: "medium",
  rating: 1400,
  tags: ["dp", "greedy"],
};

const fakeSubmitResultResponse: PvESubmitResultResponse = {
  success: true,
  elo_change: 25,
};

const fakeQuitResponse: PvEQuitResponse = {
  success: true,
};

const fakeHistoryResponse: PvEHistoryResponse = {
  items: [
    {
      session_id: "pve-session-1",
      status: "completed",
      problem_title: "Test Problem",
      difficulty: "medium",
      rating: 1400,
      tags: ["dp"],
      solved: true,
      time_spent: 300,
      attempts: 1,
      started_at: "2025-01-01T00:00:00Z",
      completed_at: "2025-01-01T00:05:00Z",
    },
  ],
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("usePvEChallengeStore", () => {
  beforeEach(() => {
    // Reset store to initial state
    usePvEChallengeStore.getState().reset();

    // Clear all mocks
    mockStartChallenge.mockReset();
    mockGetChallenge.mockReset();
    mockSubmitResult.mockReset();
    mockQuitChallenge.mockReset();
    mockGetHistory.mockReset();
    vi.clearAllMocks();
  });

  // -----------------------------------------------------------------------
  // Initial state
  // -----------------------------------------------------------------------

  describe("initial state", () => {
    it("has correct default values", () => {
      const state = usePvEChallengeStore.getState();

      expect(state.phase).toBe("idle");
      expect(state.error).toBe("");
      expect(state.sessionId).toBe("");
      expect(state.challenge).toBeNull();
      expect(state.startResponse).toBeNull();
      expect(state.revealed).toBe(false);
      expect(state.submitResult).toBeNull();
      expect(state.quitResult).toBeNull();
      expect(state.history).toBeNull();
      expect(state.historyLoading).toBe(false);
    });
  });

  // -----------------------------------------------------------------------
  // reset
  // -----------------------------------------------------------------------

  describe("reset", () => {
    it("resets all state to initial values", () => {
      usePvEChallengeStore.setState({
        phase: "result",
        error: "some error",
        sessionId: "pve-123",
        challenge: fakeDetailResponse,
        startResponse: fakeStartResponse,
        revealed: true,
        submitResult: fakeSubmitResultResponse,
        quitResult: fakeQuitResponse,
        history: fakeHistoryResponse,
        historyLoading: true,
      });

      usePvEChallengeStore.getState().reset();

      const state = usePvEChallengeStore.getState();
      expect(state.phase).toBe("idle");
      expect(state.error).toBe("");
      expect(state.sessionId).toBe("");
      expect(state.challenge).toBeNull();
      expect(state.startResponse).toBeNull();
      expect(state.revealed).toBe(false);
      expect(state.submitResult).toBeNull();
      expect(state.quitResult).toBeNull();
      expect(state.history).toBeNull();
      expect(state.historyLoading).toBe(false);
    });
  });

  // -----------------------------------------------------------------------
  // startChallenge
  // -----------------------------------------------------------------------

  describe("startChallenge", () => {
    it("sets loading phase, calls API, and transitions to in_progress", async () => {
      mockStartChallenge.mockResolvedValueOnce(fakeStartResponse);

      await usePvEChallengeStore.getState().startChallenge();

      expect(mockStartChallenge).toHaveBeenCalledOnce();

      const state = usePvEChallengeStore.getState();
      expect(state.phase).toBe("in_progress");
      expect(state.sessionId).toBe("pve-session-1");
      expect(state.startResponse).toEqual(fakeStartResponse);
      expect(state.error).toBe("");
      expect(state.revealed).toBe(false);
    });

    it("sets error and returns to idle phase on API failure with structured error", async () => {
      mockStartChallenge.mockRejectedValueOnce({
        response: {
          data: {
            error: { message: "Already in an active challenge" },
          },
        },
      });

      await usePvEChallengeStore.getState().startChallenge();

      const state = usePvEChallengeStore.getState();
      expect(state.phase).toBe("idle");
      expect(state.error).toBe("Already in an active challenge");
    });

    it("extracts error from response.data.detail", async () => {
      mockStartChallenge.mockRejectedValueOnce({
        response: {
          data: {
            detail: "Rate limited",
          },
        },
      });

      await usePvEChallengeStore.getState().startChallenge();

      const state = usePvEChallengeStore.getState();
      expect(state.phase).toBe("idle");
      expect(state.error).toBe("Rate limited");
    });

    it("uses default error message when no structured error", async () => {
      mockStartChallenge.mockRejectedValueOnce(new Error("Network error"));

      await usePvEChallengeStore.getState().startChallenge();

      const state = usePvEChallengeStore.getState();
      expect(state.phase).toBe("idle");
      expect(state.error).toBe("Failed to start PvE challenge");
    });
  });

  // -----------------------------------------------------------------------
  // fetchChallenge
  // -----------------------------------------------------------------------

  describe("fetchChallenge", () => {
    it("sets challenge and sessionId from API response", async () => {
      mockGetChallenge.mockResolvedValueOnce(fakeDetailResponse);

      await usePvEChallengeStore.getState().fetchChallenge("pve-session-1");

      const state = usePvEChallengeStore.getState();
      expect(mockGetChallenge).toHaveBeenCalledWith("pve-session-1");
      expect(state.challenge).toEqual(fakeDetailResponse);
      expect(state.sessionId).toBe("pve-session-1");
    });

    it("auto-reveals and sets result phase when challenge is completed", async () => {
      const completedDetail = { ...fakeDetailResponse, status: "completed" as const };
      mockGetChallenge.mockResolvedValueOnce(completedDetail);

      await usePvEChallengeStore.getState().fetchChallenge("pve-session-1");

      const state = usePvEChallengeStore.getState();
      expect(state.revealed).toBe(true);
      expect(state.phase).toBe("result");
    });

    it("auto-reveals and sets result phase when challenge is quit", async () => {
      const quitDetail = { ...fakeDetailResponse, status: "quit" as const };
      mockGetChallenge.mockResolvedValueOnce(quitDetail);

      await usePvEChallengeStore.getState().fetchChallenge("pve-session-1");

      const state = usePvEChallengeStore.getState();
      expect(state.revealed).toBe(true);
      expect(state.phase).toBe("result");
    });

    it("does not reveal when challenge is in_progress", async () => {
      mockGetChallenge.mockResolvedValueOnce(fakeDetailResponse); // status: "in_progress"

      await usePvEChallengeStore.getState().fetchChallenge("pve-session-1");

      const state = usePvEChallengeStore.getState();
      expect(state.revealed).toBe(false);
      expect(state.phase).toBe("idle"); // phase unchanged
    });

    it("silently handles API errors", async () => {
      mockGetChallenge.mockRejectedValueOnce(new Error("Network error"));

      // Should not throw
      await usePvEChallengeStore.getState().fetchChallenge("bad-id");

      const state = usePvEChallengeStore.getState();
      // State should remain unchanged from initial
      expect(state.challenge).toBeNull();
    });
  });

  // -----------------------------------------------------------------------
  // submitResultAction
  // -----------------------------------------------------------------------

  describe("submitResultAction", () => {
    it("submits result, fetches detail, and sets result phase", async () => {
      usePvEChallengeStore.setState({ sessionId: "pve-session-1" });

      mockSubmitResult.mockResolvedValueOnce(fakeSubmitResultResponse);
      mockGetChallenge.mockResolvedValueOnce(fakeDetailResponse);

      await usePvEChallengeStore.getState().submitResultAction(true, 300, 1, 0);

      expect(mockSubmitResult).toHaveBeenCalledWith("pve-session-1", {
        solved: true,
        time_spent: 300,
        attempts: 1,
        error_count: 0,
      });
      expect(mockGetChallenge).toHaveBeenCalledWith("pve-session-1");

      const state = usePvEChallengeStore.getState();
      expect(state.submitResult).toEqual(fakeSubmitResultResponse);
      expect(state.challenge).toEqual(fakeDetailResponse);
      expect(state.revealed).toBe(true);
      expect(state.phase).toBe("result");
    });

    it("uses default errorCount of 0 when not provided", async () => {
      usePvEChallengeStore.setState({ sessionId: "pve-session-1" });

      mockSubmitResult.mockResolvedValueOnce(fakeSubmitResultResponse);
      mockGetChallenge.mockResolvedValueOnce(fakeDetailResponse);

      await usePvEChallengeStore.getState().submitResultAction(false, 600, 3);

      expect(mockSubmitResult).toHaveBeenCalledWith("pve-session-1", {
        solved: false,
        time_spent: 600,
        attempts: 3,
        error_count: 0,
      });
    });

    it("sets error on API failure with structured error", async () => {
      usePvEChallengeStore.setState({ sessionId: "pve-session-1" });

      mockSubmitResult.mockRejectedValueOnce({
        response: {
          data: {
            error: { message: "Session expired" },
          },
        },
      });

      await usePvEChallengeStore.getState().submitResultAction(true, 300, 1);

      const state = usePvEChallengeStore.getState();
      expect(state.error).toBe("Session expired");
    });

    it("extracts error from response.data.detail on submit failure", async () => {
      usePvEChallengeStore.setState({ sessionId: "pve-session-1" });

      mockSubmitResult.mockRejectedValueOnce({
        response: {
          data: { detail: "Invalid session" },
        },
      });

      await usePvEChallengeStore.getState().submitResultAction(true, 300, 1);

      const state = usePvEChallengeStore.getState();
      expect(state.error).toBe("Invalid session");
    });

    it("uses default error message on generic failure", async () => {
      usePvEChallengeStore.setState({ sessionId: "pve-session-1" });

      mockSubmitResult.mockRejectedValueOnce(new Error("Network error"));

      await usePvEChallengeStore.getState().submitResultAction(true, 300, 1);

      const state = usePvEChallengeStore.getState();
      expect(state.error).toBe("Failed to submit result");
    });
  });

  // -----------------------------------------------------------------------
  // quitChallengeAction
  // -----------------------------------------------------------------------

  describe("quitChallengeAction", () => {
    it("quits challenge, fetches detail, and sets result phase", async () => {
      usePvEChallengeStore.setState({ sessionId: "pve-session-1" });

      mockQuitChallenge.mockResolvedValueOnce(fakeQuitResponse);
      mockGetChallenge.mockResolvedValueOnce(fakeDetailResponse);

      await usePvEChallengeStore.getState().quitChallengeAction(2);

      expect(mockQuitChallenge).toHaveBeenCalledWith("pve-session-1", 2);
      expect(mockGetChallenge).toHaveBeenCalledWith("pve-session-1");

      const state = usePvEChallengeStore.getState();
      expect(state.quitResult).toEqual(fakeQuitResponse);
      expect(state.challenge).toEqual(fakeDetailResponse);
      expect(state.revealed).toBe(true);
      expect(state.phase).toBe("result");
    });

    it("sets error on API failure with structured error", async () => {
      usePvEChallengeStore.setState({ sessionId: "pve-session-1" });

      mockQuitChallenge.mockRejectedValueOnce({
        response: {
          data: {
            error: { message: "Cannot quit" },
          },
        },
      });

      await usePvEChallengeStore.getState().quitChallengeAction(0);

      const state = usePvEChallengeStore.getState();
      expect(state.error).toBe("Cannot quit");
    });

    it("extracts error from response.data.detail on quit failure", async () => {
      usePvEChallengeStore.setState({ sessionId: "pve-session-1" });

      mockQuitChallenge.mockRejectedValueOnce({
        response: {
          data: { detail: "Session locked" },
        },
      });

      await usePvEChallengeStore.getState().quitChallengeAction(0);

      const state = usePvEChallengeStore.getState();
      expect(state.error).toBe("Session locked");
    });

    it("uses default error message on generic failure", async () => {
      usePvEChallengeStore.setState({ sessionId: "pve-session-1" });

      mockQuitChallenge.mockRejectedValueOnce(new Error("Network error"));

      await usePvEChallengeStore.getState().quitChallengeAction(0);

      const state = usePvEChallengeStore.getState();
      expect(state.error).toBe("Failed to quit challenge");
    });
  });

  // -----------------------------------------------------------------------
  // fetchHistory
  // -----------------------------------------------------------------------

  describe("fetchHistory", () => {
    it("fetches history with default pagination", async () => {
      mockGetHistory.mockResolvedValueOnce(fakeHistoryResponse);

      await usePvEChallengeStore.getState().fetchHistory();

      expect(mockGetHistory).toHaveBeenCalledWith(1, 20);

      const state = usePvEChallengeStore.getState();
      expect(state.history).toEqual(fakeHistoryResponse);
      expect(state.historyLoading).toBe(false);
    });

    it("fetches history with custom pagination", async () => {
      mockGetHistory.mockResolvedValueOnce(fakeHistoryResponse);

      await usePvEChallengeStore.getState().fetchHistory(3, 10);

      expect(mockGetHistory).toHaveBeenCalledWith(3, 10);
    });

    it("sets historyLoading to false on failure", async () => {
      mockGetHistory.mockRejectedValueOnce(new Error("Network error"));

      await usePvEChallengeStore.getState().fetchHistory();

      const state = usePvEChallengeStore.getState();
      expect(state.historyLoading).toBe(false);
      // History should remain null (initial state)
      expect(state.history).toBeNull();
    });
  });
});
