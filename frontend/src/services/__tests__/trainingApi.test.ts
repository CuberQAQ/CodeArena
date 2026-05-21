import { describe, it, expect, vi, beforeEach } from "vitest";
import { getMElo } from "../trainingApi";

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
});
