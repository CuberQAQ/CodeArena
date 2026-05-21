import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  freePlaySearch,
  freePlayRecommend,
  freePlayStart,
  freePlaySubmit,
  freePlayQuit,
} from "../freePlayApi";

// ---------------------------------------------------------------------------
// Mock the api module so no real HTTP requests are made
// ---------------------------------------------------------------------------

const mockPost = vi.fn();

vi.mock("@/services/api", () => ({
  default: {
    post: (...args: unknown[]) => mockPost(...args),
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

describe("freePlayApi", () => {
  beforeEach(() => {
    mockPost.mockReset();
    vi.clearAllMocks();
  });

  // -----------------------------------------------------------------------
  // freePlaySearch
  // -----------------------------------------------------------------------

  describe("freePlaySearch", () => {
    it("calls api.post with correct URL and params", async () => {
      const fakeResponse = { problems: [{ contest_id: 123, index: "A", name: "Test Problem", rating: 1200, tags: ["dp"] }] };
      mockPost.mockResolvedValueOnce(makeApiReply(fakeResponse));

      const result = await freePlaySearch(800, 1500, ["dp", "greedy"]);

      expect(mockPost).toHaveBeenCalledWith("/free-play/search", {
        min_rating: 800,
        max_rating: 1500,
        tags: ["dp", "greedy"],
      });
      expect(result).toEqual(fakeResponse);
    });

    it("propagates errors from api.post", async () => {
      mockPost.mockRejectedValueOnce(new Error("Server error"));

      await expect(freePlaySearch(800, 1500, [])).rejects.toThrow("Server error");
    });
  });

  // -----------------------------------------------------------------------
  // freePlayRecommend
  // -----------------------------------------------------------------------

  describe("freePlayRecommend", () => {
    it("calls api.post with correct URL and returns data", async () => {
      const fakeResponse = {
        problem_contest_id: 456,
        problem_index: "B",
        problem_name: "Recommended Problem",
        problem_rating: 1300,
        problem_tags: ["math"],
      };
      mockPost.mockResolvedValueOnce(makeApiReply(fakeResponse));

      const result = await freePlayRecommend();

      expect(mockPost).toHaveBeenCalledWith("/free-play/recommend");
      expect(result).toEqual(fakeResponse);
    });

    it("propagates errors from api.post", async () => {
      mockPost.mockRejectedValueOnce(new Error("No recommendation"));

      await expect(freePlayRecommend()).rejects.toThrow("No recommendation");
    });
  });

  // -----------------------------------------------------------------------
  // freePlayStart
  // -----------------------------------------------------------------------

  describe("freePlayStart", () => {
    it("calls api.post with correct URL and params", async () => {
      const fakeResponse = { session_id: "fp-session-1" };
      mockPost.mockResolvedValueOnce(makeApiReply(fakeResponse));

      const params = {
        problem_contest_id: 789,
        problem_index: "C",
        problem_rating: 1400,
        problem_tags: ["graphs"],
        problem_name: "Graph Problem",
      };

      const result = await freePlayStart(params);

      expect(mockPost).toHaveBeenCalledWith("/free-play/start", params);
      expect(result).toEqual(fakeResponse);
    });

    it("propagates errors from api.post", async () => {
      mockPost.mockRejectedValueOnce(new Error("Already in session"));

      await expect(
        freePlayStart({
          problem_contest_id: 1,
          problem_index: "A",
          problem_rating: 800,
          problem_tags: [],
          problem_name: "Test",
        }),
      ).rejects.toThrow("Already in session");
    });
  });

  // -----------------------------------------------------------------------
  // freePlaySubmit
  // -----------------------------------------------------------------------

  describe("freePlaySubmit", () => {
    it("calls api.post with correct URL and params", async () => {
      const fakeResponse = { success: true, elo_change: 15 };
      mockPost.mockResolvedValueOnce(makeApiReply(fakeResponse));

      const params = { solved: true, time_spent: 300, attempts: 1, error_count: 0 };

      const result = await freePlaySubmit("fp-session-1", params);

      expect(mockPost).toHaveBeenCalledWith("/free-play/fp-session-1/submit", params);
      expect(result).toEqual(fakeResponse);
    });

    it("propagates errors from api.post", async () => {
      mockPost.mockRejectedValueOnce(new Error("Session not found"));

      await expect(
        freePlaySubmit("bad-session", { solved: false, time_spent: 100, attempts: 3, error_count: 2 }),
      ).rejects.toThrow("Session not found");
    });
  });

  // -----------------------------------------------------------------------
  // freePlayQuit
  // -----------------------------------------------------------------------

  describe("freePlayQuit", () => {
    it("calls api.post with correct URL and returns data", async () => {
      const fakeResponse = { success: true };
      mockPost.mockResolvedValueOnce(makeApiReply(fakeResponse));

      const result = await freePlayQuit("fp-session-1");

      expect(mockPost).toHaveBeenCalledWith("/free-play/fp-session-1/quit");
      expect(result).toEqual(fakeResponse);
    });

    it("propagates errors from api.post", async () => {
      mockPost.mockRejectedValueOnce(new Error("Cannot quit"));

      await expect(freePlayQuit("bad-session")).rejects.toThrow("Cannot quit");
    });
  });
});
