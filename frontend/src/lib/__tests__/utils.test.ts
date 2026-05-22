import { describe, it, expect } from "vitest";
import { cn } from "@/lib/utils";

describe("cn", () => {
  it("merges class names", () => {
    expect(cn("foo", "bar")).toBe("foo bar");
  });

  it("handles conditional classes via clsx", () => {
    const showHidden = false;
    expect(cn("base", showHidden && "hidden", "extra")).toBe("base extra");
  });

  it("deduplicates conflicting tailwind utilities via twMerge", () => {
    // twMerge should keep the last conflicting utility
    expect(cn("px-2", "px-4")).toBe("px-4");
    expect(cn("p-2", "px-4")).toBe("p-2 px-4");
  });

  it("handles empty input", () => {
    expect(cn()).toBe("");
  });

  it("handles undefined and null inputs", () => {
    expect(cn("base", undefined, null, "end")).toBe("base end");
  });

  it("handles array inputs", () => {
    expect(cn(["foo", "bar"], "baz")).toBe("foo bar baz");
  });
});
