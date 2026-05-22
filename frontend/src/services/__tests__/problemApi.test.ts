import { describe, it, expect, vi, beforeEach } from "vitest";
import api from "@/services/api";

// Mock the api module
vi.mock("@/services/api", () => ({
  default: {
    get: vi.fn(),
  },
}));

import { getProblemStatement, checkProblemCache } from "@/services/problemApi";

describe("problemApi", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("getProblemStatement", () => {
    it("fetches problem statement by problem ID", async () => {
      const mockData = {
        problem_id: "1920A",
        contest_id: 1920,
        index: "A",
        title: "Two Sum",
        time_limit: "1 second",
        memory_limit: "256 MB",
        body_html: "<p>Solve Two Sum</p>",
        input_spec_html: "<p>Input</p>",
        output_spec_html: "<p>Output</p>",
        samples: [{ input: "4\n2 7 11 15\n9", output: "0 1" }],
        note_html: null,
        full_html: "<p>Full problem</p>",
        scraped_at: "2025-01-01T00:00:00Z",
        cached: true,
        fallback_url: "https://codeforces.com/1920/A",
      };

      vi.mocked(api.get).mockResolvedValue({
        data: { success: true, data: mockData, message: "ok" },
      });

      const result = await getProblemStatement("1920A");

      expect(api.get).toHaveBeenCalledWith("/problem/1920A/statement");
      expect(result).toEqual(mockData);
      expect(result.problem_id).toBe("1920A");
      expect(result.cached).toBe(true);
    });

    it("handles problem without optional fields", async () => {
      const mockData = {
        problem_id: "1900B",
        contest_id: 1900,
        index: "B",
        title: "Simple Problem",
        time_limit: null,
        memory_limit: null,
        body_html: "<p>Test</p>",
        input_spec_html: null,
        output_spec_html: null,
        samples: [],
        note_html: null,
        full_html: "<p>Full</p>",
        scraped_at: "2025-01-01T00:00:00Z",
        cached: false,
        fallback_url: "https://codeforces.com/1900/B",
      };

      vi.mocked(api.get).mockResolvedValue({
        data: { success: true, data: mockData, message: "ok" },
      });

      const result = await getProblemStatement("1900B");

      expect(result.time_limit).toBeNull();
      expect(result.memory_limit).toBeNull();
      expect(result.samples).toEqual([]);
    });
  });

  describe("checkProblemCache", () => {
    it("checks cache status for multiple problem IDs", async () => {
      const mockResult = {
        cached: ["1920A", "1920B"],
        not_cached: ["1920C"],
      };

      vi.mocked(api.get).mockResolvedValue({
        data: { success: true, data: mockResult, message: "ok" },
      });

      const result = await checkProblemCache(["1920A", "1920B", "1920C"]);

      expect(api.get).toHaveBeenCalledWith("/problem/statements/check", {
        params: { problem_ids: "1920A,1920B,1920C" },
      });
      expect(result.cached).toEqual(["1920A", "1920B"]);
      expect(result.not_cached).toEqual(["1920C"]);
    });

    it("handles single problem ID", async () => {
      const mockResult = { cached: ["1920A"], not_cached: [] };

      vi.mocked(api.get).mockResolvedValue({
        data: { success: true, data: mockResult, message: "ok" },
      });

      const _result = await checkProblemCache(["1920A"]);

      expect(api.get).toHaveBeenCalledWith("/problem/statements/check", {
        params: { problem_ids: "1920A" },
      });
    });

    it("handles empty array", async () => {
      const mockResult = { cached: [], not_cached: [] };

      vi.mocked(api.get).mockResolvedValue({
        data: { success: true, data: mockResult, message: "ok" },
      });

      const result = await checkProblemCache([]);

      expect(result.cached).toEqual([]);
    });
  });
});
