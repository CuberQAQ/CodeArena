import { describe, it, expect, vi, beforeAll } from "vitest";
import { renderHook } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

let mockReducedMotion = false;

// Mock matchMedia for jsdom
beforeAll(() => {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (query: string) => ({
      matches: mockReducedMotion,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  });
});

vi.mock("framer-motion", () => ({
  useReducedMotion: () => mockReducedMotion,
}));

// ---------------------------------------------------------------------------
// Import SUTs
// ---------------------------------------------------------------------------

import {
  usePrefersReducedMotion,
  useAnimationScale,
  useSpringTransition,
  useTweenTransition,
} from "@/hooks/useAnimation";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("usePrefersReducedMotion", () => {
  it("returns false when framer-motion returns false and system does not prefer reduced", () => {
    mockReducedMotion = false;
    const { result } = renderHook(() => usePrefersReducedMotion());
    expect(result.current).toBe(false);
  });
});

describe("useAnimationScale", () => {
  it("returns 1 when reduced motion is false", () => {
    mockReducedMotion = false;
    const { result } = renderHook(() => useAnimationScale());
    expect(result.current).toBe(1);
  });

  it("returns 0 when reduced motion is true", () => {
    mockReducedMotion = true;
    const { result } = renderHook(() => useAnimationScale());
    expect(result.current).toBe(0);
  });
});

describe("useSpringTransition", () => {
  it("returns spring transition when reduced motion is false", () => {
    mockReducedMotion = false;
    const { result } = renderHook(() => useSpringTransition());
    expect(result.current).toEqual({
      type: "spring",
      stiffness: 300,
      damping: 30,
    });
  });

  it("returns zero duration when reduced motion is true", () => {
    mockReducedMotion = true;
    const { result } = renderHook(() => useSpringTransition());
    expect(result.current).toEqual({ duration: 0 });
  });
});

describe("useTweenTransition", () => {
  it("returns tween transition with default duration", () => {
    mockReducedMotion = false;
    const { result } = renderHook(() => useTweenTransition());
    expect(result.current).toEqual({ duration: 0.3, ease: "easeOut" });
  });

  it("returns tween transition with custom duration", () => {
    mockReducedMotion = false;
    const { result } = renderHook(() => useTweenTransition(0.5));
    expect(result.current).toEqual({ duration: 0.5, ease: "easeOut" });
  });

  it("returns zero duration when reduced motion is true", () => {
    mockReducedMotion = true;
    const { result } = renderHook(() => useTweenTransition(0.5));
    expect(result.current).toEqual({ duration: 0 });
  });
});
