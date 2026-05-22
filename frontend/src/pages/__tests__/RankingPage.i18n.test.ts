import { describe, it, expect } from "vitest";
import enRanking from "@/locales/en/ranking.json";
import zhRanking from "@/locales/zh/ranking.json";

/**
 * Verify that ranking locale files have consistent keys and correct content
 * for the title-switching feature (FR-20.1, FR-21.3).
 */
describe("RankingPage i18n locale completeness", () => {
  const requiredKeys = [
    "title",
    "description",
    "arenaTitle",
    "arenaDescription",
    "tabGlobal",
    "tabArena",
    "globalDesc",
    "arenaDesc",
  ];

  it("en locale has all required keys", () => {
    for (const key of requiredKeys) {
      expect(enRanking[key as keyof typeof enRanking]).toBeDefined();
      expect(typeof enRanking[key as keyof typeof enRanking]).toBe("string");
      expect(enRanking[key as keyof typeof enRanking].length).toBeGreaterThan(0);
    }
  });

  it("zh locale has all required keys", () => {
    for (const key of requiredKeys) {
      expect(zhRanking[key as keyof typeof zhRanking]).toBeDefined();
      expect(typeof zhRanking[key as keyof typeof zhRanking]).toBe("string");
      expect(zhRanking[key as keyof typeof zhRanking].length).toBeGreaterThan(0);
    }
  });

  it("en locale has correct global title", () => {
    expect(enRanking.title).toBe("Global Ranking");
  });

  it("en locale has correct arena title", () => {
    expect(enRanking.arenaTitle).toBe("Arena Ranking");
  });

  it("zh locale has correct global title", () => {
    expect(zhRanking.title).toBe("全球排名");
  });

  it("zh locale has correct arena title", () => {
    expect(zhRanking.arenaTitle).toBe("竞技场排名");
  });

  it("en and zh locales have the same keys", () => {
    const enKeys = Object.keys(enRanking).sort();
    const zhKeys = Object.keys(zhRanking).sort();
    expect(enKeys).toEqual(zhKeys);
  });

  it("arena titles are different from global titles in both languages", () => {
    expect(enRanking.title).not.toBe(enRanking.arenaTitle);
    expect(zhRanking.title).not.toBe(zhRanking.arenaTitle);
  });

  it("arena descriptions are different from global descriptions in both languages", () => {
    expect(enRanking.description).not.toBe(enRanking.arenaDescription);
    expect(zhRanking.description).not.toBe(zhRanking.arenaDescription);
  });
});
