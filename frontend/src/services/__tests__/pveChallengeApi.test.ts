import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  startChallenge,
  getChallenge,
  submitResult,
  quitChallenge,
  getHistory,
} from "../pveChallengeApi";

// ---------------------------------------------------------------------------
// Mock the api module so no real HTTP requests are made
// ---------------------------------------------------------------------------

const mockPost = vi.fn();
const mockGet = vi.fn();

vi.mock("@/services/api", () => ({
  default: {
    post: (...args: unknown[]) => mockPost(...args),
    get: (...args: unknown[]) => mockGet(...args),
  },
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeApiReply<T>(data: T) {
  return { data: { success: true, data, message: "ok" } };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("pveChallengeApi", () => {
  beforeEach(() => {
    mockPost.mockReset();
    mockGet.mockReset();
    vi.clearAllMocks();
  });

  // -----------------------------------------------------------------------
  // startChallenge
  // -----------------------------------------------------------------------

  describe("startChallenge", () => {
    it("calls api.post with correct URL and returns data", async () => {
      const fakeResponse = { session_id: "pve-123" };
      mockPost.mockResolvedValueOnce(makeApiReply(fakeResponse));

      const result = await startChallenge();

      expect(mockPost).toHaveBeenCalledWith("/pve-challenge/start");
      expect(result).toEqual(fakeResponse);
    });

    it("propagates errors from api.post", async () => {
      mockPost.mockRejectedValueOnce(new Error("Already in challenge"));

      await expect(startChallenge()).rejects.toThrow("Already in challenge");
    });
  });

  // -----------------------------------------------------------------------
  // getChallenge
  // -----------------------------------------------------------------------

  describe("getChallenge", () => {
    it("calls api.get with correct URL and returns data", async () => {
      const fakeResponse = {
        session_id: "pve-123",
        status: "in_progress",
        problem_title: "Test Problem",
        problem_description: "Solve this",
        started_at: "2025-01-01T00:00:00Z",
        time_limit: 1800,
        difficulty: "medium",
        rating: 1400,
        tags: ["dp"],
      };
      mockGet.mockResolvedValueOnce(makeApiReply(fakeResponse));

      const result = await getChallenge("pve-123");

      expect(mockGet).toHaveBeenCalledWith("/pve-challenge/pve-123");
      expect(result).toEqual(fakeResponse);
    });

    it("propagates errors from api.get", async () => {
      mockGet.mockRejectedValueOnce(new Error("Not found"));

      await expect(getChallenge("bad-id")).rejects.toThrow("Not found");
    });
  });

  // -----------------------------------------------------------------------
  // submitResult
  // -----------------------------------------------------------------------

  describe("submitResult", () => {
    it("calls api.post with correct URL and params", async () => {
      const fakeResponse = { success: true, elo_change: 20 };
      mockPost.mockResolvedValueOnce(makeApiReply(fakeResponse));

      const params = { solved: true, time_spent: 300, attempts: 1, error_count: 0 };

      const result = await submitResult("pve-123", params);

      expect(mockPost).toHaveBeenCalledWith("/pve-challenge/pve-123/submit", params);
      expect(result).toEqual(fakeResponse);
    });

    it("passes optional error_count parameter", async () => {
      const fakeResponse = { success: true, elo_change: 10 };
      mockPost.mockResolvedValueOnce(makeApiReply(fakeResponse));

      const params = { solved: false, time_spent: 600, attempts: 5, error_count: 3 };

      const result = await submitResult("pve-456", params);

      expect(mockPost).toHaveBeenCalledWith("/pve-challenge/pve-456/submit", params);
      expect(result).toEqual(fakeResponse);
    });

    it("propagates errors from api.post", async () => {
      mockPost.mockRejectedValueOnce(new Error("Submit failed"));

      await expect(
        submitResult("bad-id", { solved: true, time_spent: 100, attempts: 1 }),
      ).rejects.toThrow("Submit failed");
    });
  });

  // -----------------------------------------------------------------------
  // quitChallenge
  // -----------------------------------------------------------------------

  describe("quitChallenge", () => {
    it("calls api.post with correct URL and params", async () => {
      const fakeResponse = { success: true };
      mockPost.mockResolvedValueOnce(makeApiReply(fakeResponse));

      const result = await quitChallenge("pve-123", 2);

      expect(mockPost).toHaveBeenCalledWith("/pve-challenge/pve-123/quit", {
        submissions: 2,
      });
      expect(result).toEqual(fakeResponse);
    });

    it("propagates errors from api.post", async () => {
      mockPost.mockRejectedValueOnce(new Error("Quit failed"));

      await expect(quitChallenge("bad-id", 0)).rejects.toThrow("Quit failed");
    });
  });

  // -----------------------------------------------------------------------
  // getHistory
  // -----------------------------------------------------------------------

  describe("getHistory", () => {
    it("calls api.get with default pagination params", async () => {
      const fakeResponse = { items: [], total: 0, page: 1, page_size: 20 };
      mockGet.mockResolvedValueOnce(makeApiReply(fakeResponse));

      const result = await getHistory();

      expect(mockGet).toHaveBeenCalledWith("/pve-challenge/history", {
        params: { page: 1, page_size: 20 },
      });
      expect(result).toEqual(fakeResponse);
    });

    it("calls api.get with custom pagination params", async () => {
      const fakeResponse = { items: [], total: 100, page: 3, page_size: 10 };
      mockGet.mockResolvedValueOnce(makeApiReply(fakeResponse));

      const result = await getHistory(3, 10);

      expect(mockGet).toHaveBeenCalledWith("/pve-challenge/history", {
        params: { page: 3, page_size: 10 },
      });
      expect(result).toEqual(fakeResponse);
    });

    it("propagates errors from api.get", async () => {
      mockGet.mockRejectedValueOnce(new Error("History unavailable"));

      await expect(getHistory()).rejects.toThrow("History unavailable");
    });
  });
});
