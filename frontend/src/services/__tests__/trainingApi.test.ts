import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  getMElo,
  getActiveTrainingSession,
  getRecommendedTopics,
  getRecommendedProblem,
  getCuratedProblems,
} from "../trainingApi";

// ---------------------------------------------------------------------------
// Mock the api module so no real HTTP requests are made
// ---------------------------------------------------------------------------

const mockGet = vi.fn();

vi.mock("@/services/api", () => ({
  default: {
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

describe("trainingApi", () => {
  beforeEach(() => {
    mockGet.mockReset();
    vi.clearAllMocks();
  });

  // -----------------------------------------------------------------------
  // getMElo
  // -----------------------------------------------------------------------

  describe("getMElo", () => {
    it("calls api.get with correct URL and returns MElo data", async () => {
      const fakeResponse = {
        tags: [
          { tag: "dp", elo: 1500, games: 20 },
          { tag: "greedy", elo: 1400, games: 15 },
          { tag: "graphs", elo: 1300, games: 10 },
        ],
      };
      mockGet.mockResolvedValueOnce(makeApiReply(fakeResponse));

      const result = await getMElo();

      expect(mockGet).toHaveBeenCalledWith("/training/melo");
      expect(result).toEqual(fakeResponse);
    });

    it("propagates errors from api.get", async () => {
      mockGet.mockRejectedValueOnce(new Error("MElo unavailable"));

      await expect(getMElo()).rejects.toThrow("MElo unavailable");
    });
  });

  // -----------------------------------------------------------------------
  // getActiveTrainingSession
  // -----------------------------------------------------------------------

  describe("getActiveTrainingSession", () => {
    it("fetches active session for a topic", async () => {
      const mockSession = {
        session_id: "sess-1",
        topic_id: "dp",
        problem: { name: "Two Sum", contest_id: 1, index: "A", rating: 1200 },
        started_at: "2025-01-01T00:00:00Z",
      };

      mockGet.mockResolvedValueOnce(makeApiReply(mockSession));

      const result = await getActiveTrainingSession("dp");

      expect(mockGet).toHaveBeenCalledWith("/training/topics/dp/active-session");
      expect(result).toEqual(mockSession);
    });

    it("returns null when no active session", async () => {
      mockGet.mockResolvedValueOnce(makeApiReply(null));

      const result = await getActiveTrainingSession("graphs");

      expect(result).toBeNull();
    });
  });

  // -----------------------------------------------------------------------
  // getRecommendedTopics
  // -----------------------------------------------------------------------

  describe("getRecommendedTopics", () => {
    it("fetches recommended topics with default limit", async () => {
      const mockTopics = [
        { topic_id: "dp", name: "DP", reason: "Weakest area", priority: 1 },
      ];

      mockGet.mockResolvedValueOnce(makeApiReply(mockTopics));

      const result = await getRecommendedTopics();

      expect(mockGet).toHaveBeenCalledWith("/training/recommended-topics", {
        params: { limit: 3 },
      });
      expect(result).toEqual(mockTopics);
    });

    it("fetches with custom limit", async () => {
      mockGet.mockResolvedValueOnce(makeApiReply([]));

      await getRecommendedTopics(5);

      expect(mockGet).toHaveBeenCalledWith("/training/recommended-topics", {
        params: { limit: 5 },
      });
    });
  });

  // -----------------------------------------------------------------------
  // getRecommendedProblem
  // -----------------------------------------------------------------------

  describe("getRecommendedProblem", () => {
    it("fetches recommended problem for a topic", async () => {
      const mockProblem = {
        problem_id: "1920A",
        name: "Two Sum",
        contest_id: 1920,
        index: "A",
        rating: 1200,
        url: "https://codeforces.com/1920/A",
      };

      mockGet.mockResolvedValueOnce(makeApiReply(mockProblem));

      const result = await getRecommendedProblem("dp");

      expect(mockGet).toHaveBeenCalledWith("/training/topics/dp/recommend", { params: {} });
      expect(result).toEqual(mockProblem);
    });

    it("returns null when no recommendation available", async () => {
      mockGet.mockResolvedValueOnce(makeApiReply(null));

      const result = await getRecommendedProblem("math");
      expect(result).toBeNull();
    });
  });

  // -----------------------------------------------------------------------
  // getCuratedProblems
  // -----------------------------------------------------------------------

  describe("getCuratedProblems", () => {
    it("fetches curated problems for a topic with default params", async () => {
      const mockResponse = {
        problems: [
          { problem_id: "1920A", name: "Two Sum", rating: 1200 },
        ],
        total: 1,
        offset: 0,
        limit: 20,
      };

      mockGet.mockResolvedValueOnce(makeApiReply(mockResponse));

      const result = await getCuratedProblems("dp");

      expect(mockGet).toHaveBeenCalledWith("/training/topics/dp/curated-problems", {
        params: undefined,
      });
      expect(result).toEqual(mockResponse);
    });

    it("fetches with custom pagination and rating filters", async () => {
      mockGet.mockResolvedValueOnce(
        makeApiReply({ problems: [], total: 0, offset: 10, limit: 5 }),
      );

      await getCuratedProblems("graphs", {
        limit: 5,
        offset: 10,
        min_rating: 1200,
        max_rating: 1800,
      });

      expect(mockGet).toHaveBeenCalledWith("/training/topics/graphs/curated-problems", {
        params: { limit: 5, offset: 10, min_rating: 1200, max_rating: 1800 },
      });
    });
  });
});
