import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";

// ---------------------------------------------------------------------------
// SUT
// ---------------------------------------------------------------------------

import { useInstallPrompt } from "@/hooks/useInstallPrompt";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const DISMISSED_AT_KEY = "pwa_install_dismissed_at";

/** Create a fake BeforeInstallPromptEvent-like object. */
function fakePromptEvent() {
  return Object.assign(new Event("beforeinstallprompt"), {
    prompt: vi.fn().mockResolvedValue(undefined),
    userChoice: Promise.resolve({ outcome: "accepted", platform: "web" }),
    platforms: ["web"],
  });
}

function mockMatchMedia(overrides?: { matches?: boolean }) {
  return vi.fn().mockImplementation((query: string) => ({
    matches: query === "(display-mode: standalone)" ? (overrides?.matches ?? false) : false,
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    onchange: null,
    dispatchEvent: vi.fn(),
  }));
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("useInstallPrompt", () => {
  let matchMediaSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    localStorage.clear();
    matchMediaSpy = mockMatchMedia();
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: matchMediaSpy,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // -------------------------------------------------------------------------
  // Initial state
  // -------------------------------------------------------------------------

  it("returns canInstall=false when no beforeinstallprompt event has fired", () => {
    const { result } = renderHook(() => useInstallPrompt());
    expect(result.current.canInstall).toBe(false);
    expect(result.current.isInstalled).toBe(false);
  });

  it("detects standalone display mode on init", () => {
    // Re-mock matchMedia to return standalone=true
    matchMediaSpy = mockMatchMedia({ matches: true });
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: matchMediaSpy,
    });

    const { result } = renderHook(() => useInstallPrompt());
    expect(result.current.isInstalled).toBe(true);
    expect(result.current.canInstall).toBe(false);
  });

  // -------------------------------------------------------------------------
  // beforeinstallprompt
  // -------------------------------------------------------------------------

  it("sets canInstall=true when beforeinstallprompt fires", () => {
    const { result } = renderHook(() => useInstallPrompt());

    act(() => {
      window.dispatchEvent(fakePromptEvent());
    });

    expect(result.current.canInstall).toBe(true);
  });

  // -------------------------------------------------------------------------
  // promptInstall
  // -------------------------------------------------------------------------

  it("promptInstall() triggers the native prompt", async () => {
    const { result } = renderHook(() => useInstallPrompt());
    const evt = fakePromptEvent();

    act(() => {
      window.dispatchEvent(evt);
    });

    let ok = false;
    await act(async () => {
      ok = await result.current.promptInstall();
    });

    expect(ok).toBe(true);
    expect(evt.prompt).toHaveBeenCalled();
  });

  it("promptInstall() returns false if no deferred prompt", async () => {
    const { result } = renderHook(() => useInstallPrompt());

    let ok = true;
    await act(async () => {
      ok = await result.current.promptInstall();
    });

    expect(ok).toBe(false);
  });

  // -------------------------------------------------------------------------
  // dismiss + cooldown
  // -------------------------------------------------------------------------

  it("dismiss() hides the banner and writes localStorage", () => {
    const { result } = renderHook(() => useInstallPrompt());

    act(() => {
      window.dispatchEvent(fakePromptEvent());
    });
    expect(result.current.canInstall).toBe(true);

    act(() => {
      result.current.dismiss();
    });
    expect(result.current.canInstall).toBe(false);
    expect(localStorage.getItem(DISMISSED_AT_KEY)).not.toBeNull();
  });

  it("stays dismissed within the 7-day cooldown", () => {
    // Set dismissal timestamp to 3 days ago
    const threeDaysAgo = Date.now() - 3 * 24 * 60 * 60 * 1000;
    localStorage.setItem(DISMISSED_AT_KEY, String(threeDaysAgo));

    const { result } = renderHook(() => useInstallPrompt());

    act(() => {
      window.dispatchEvent(fakePromptEvent());
    });

    // Should remain hidden because still in cooldown
    expect(result.current.canInstall).toBe(false);
  });

  it("shows banner again after cooldown expires", () => {
    // Set dismissal timestamp to 8 days ago
    const eightDaysAgo = Date.now() - 8 * 24 * 60 * 60 * 1000;
    localStorage.setItem(DISMISSED_AT_KEY, String(eightDaysAgo));

    const { result } = renderHook(() => useInstallPrompt());

    act(() => {
      window.dispatchEvent(fakePromptEvent());
    });

    expect(result.current.canInstall).toBe(true);
  });

  // -------------------------------------------------------------------------
  // appinstalled
  // -------------------------------------------------------------------------

  it("appinstalled event clears the deferred prompt and sets isInstalled", () => {
    const { result } = renderHook(() => useInstallPrompt());

    act(() => {
      window.dispatchEvent(fakePromptEvent());
    });
    expect(result.current.canInstall).toBe(true);

    act(() => {
      window.dispatchEvent(new Event("appinstalled"));
    });

    expect(result.current.isInstalled).toBe(true);
    expect(result.current.canInstall).toBe(false);
  });

  // -------------------------------------------------------------------------
  // display-mode: standalone change
  // -------------------------------------------------------------------------

  it("responds to display-mode media query changes", () => {
    let listener: ((e: MediaQueryListEvent) => void) | undefined;
    const mockMql = {
      matches: false,
      media: "(display-mode: standalone)",
      addEventListener: vi.fn((_type: string, handler: (e: MediaQueryListEvent) => void) => {
        listener = handler;
      }),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      onchange: null,
      dispatchEvent: vi.fn(),
    };

    // Override the default matchMedia to return our custom mock for standalone query
    const customMatchMedia = vi.fn().mockImplementation((query: string) => {
      if (query === "(display-mode: standalone)") return mockMql;
      return {
        matches: false,
        media: query,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        addListener: vi.fn(),
        removeListener: vi.fn(),
        onchange: null,
        dispatchEvent: vi.fn(),
      };
    });
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: customMatchMedia,
    });

    const { result } = renderHook(() => useInstallPrompt());

    expect(result.current.isInstalled).toBe(false);

    // Simulate the display-mode changing to standalone
    act(() => {
      if (listener) {
        listener({ matches: true } as MediaQueryListEvent);
      }
    });

    expect(result.current.isInstalled).toBe(true);
  });
});
