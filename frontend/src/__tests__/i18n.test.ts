import { describe, it, expect, vi, beforeAll } from "vitest";

// Mock the JSON imports to avoid loading actual locale files
vi.mock("@/locales/en/common.json", () => ({ default: { app: { name: "Code Arena" } } }));
vi.mock("@/locales/en/nav.json", () => ({ default: {} }));
vi.mock("@/locales/en/auth.json", () => ({ default: { platformSlogan: "Level up your coding" } }));
vi.mock("@/locales/en/dashboard.json", () => ({ default: {} }));
vi.mock("@/locales/en/challenge.json", () => ({ default: {} }));
vi.mock("@/locales/en/training.json", () => ({ default: {} }));
vi.mock("@/locales/en/contest.json", () => ({ default: {} }));
vi.mock("@/locales/en/profile.json", () => ({ default: {} }));
vi.mock("@/locales/en/leaderboard.json", () => ({ default: {} }));
vi.mock("@/locales/en/admin.json", () => ({ default: {} }));
vi.mock("@/locales/en/rating.json", () => ({ default: {} }));
vi.mock("@/locales/en/free_play.json", () => ({ default: {} }));
vi.mock("@/locales/en/medal.json", () => ({ default: {} }));
vi.mock("@/locales/en/ranking.json", () => ({ default: {} }));

vi.mock("@/locales/zh/common.json", () => ({ default: { app: { name: "Code Arena" } } }));
vi.mock("@/locales/zh/nav.json", () => ({ default: {} }));
vi.mock("@/locales/zh/auth.json", () => ({ default: { platformSlogan: "提升你的编程" } }));
vi.mock("@/locales/zh/dashboard.json", () => ({ default: {} }));
vi.mock("@/locales/zh/challenge.json", () => ({ default: {} }));
vi.mock("@/locales/zh/training.json", () => ({ default: {} }));
vi.mock("@/locales/zh/contest.json", () => ({ default: {} }));
vi.mock("@/locales/zh/profile.json", () => ({ default: {} }));
vi.mock("@/locales/zh/leaderboard.json", () => ({ default: {} }));
vi.mock("@/locales/zh/admin.json", () => ({ default: {} }));
vi.mock("@/locales/zh/rating.json", () => ({ default: {} }));
vi.mock("@/locales/zh/free_play.json", () => ({ default: {} }));
vi.mock("@/locales/zh/medal.json", () => ({ default: {} }));
vi.mock("@/locales/zh/ranking.json", () => ({ default: {} }));

describe("i18n configuration", () => {
  let i18n: typeof import("@/i18n").default;

  beforeAll(async () => {
    const mod = await import("@/i18n");
    i18n = mod.default;
  });

  it("initializes i18n with fallback language en", () => {
    // i18next normalizes fallbackLng to an array
    const fallbackLng = i18n.options.fallbackLng;
    expect(fallbackLng).toContain("en");
  });

  it("has both en and zh resources", () => {
    const resources = i18n.options.resources as Record<string, Record<string, unknown>>;
    expect(resources).toBeDefined();
    expect(resources.en).toBeDefined();
    expect(resources.zh).toBeDefined();
  });

  it("configures expected namespaces", () => {
    const ns = i18n.options.ns as string[];
    const expectedNamespaces = [
      "common", "nav", "auth", "dashboard", "challenge", "training",
      "contest", "profile", "leaderboard", "admin", "rating", "free_play",
      "medal", "ranking",
    ];
    for (const namespace of expectedNamespaces) {
      expect(ns).toContain(namespace);
    }
  });

  it("sets default namespace to common", () => {
    expect(i18n.options.defaultNS).toBe("common");
  });

  it("disables interpolation escaping", () => {
    const interpolation = i18n.options.interpolation as Record<string, unknown>;
    expect(interpolation.escapeValue).toBe(false);
  });

  it("has language detection configured with localStorage and navigator", () => {
    const detection = i18n.options.detection as Record<string, unknown>;
    expect(detection).toBeDefined();
    expect(detection.order).toContain("localStorage");
    expect(detection.order).toContain("navigator");
    expect(detection.caches).toContain("localStorage");
    expect(detection.lookupLocalStorage).toBe("i18nextLng");
  });
});
