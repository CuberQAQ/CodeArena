import { useState, useEffect, useCallback, useRef } from "react";

const DISMISSED_AT_KEY = "pwa_install_dismissed_at";
const COOLDOWN_MS = 7 * 24 * 60 * 60 * 1000; // 7 days

export interface UseInstallPromptReturn {
  canInstall: boolean;
  isInstalled: boolean;
  promptInstall: () => Promise<boolean>;
  dismiss: () => void;
}

/**
 * Hook that manages the PWA install prompt lifecycle.
 *
 * - Listens for `beforeinstallprompt` and keeps the event reference.
 * - Detects whether the app is already running in standalone mode.
 * - Tracks a 7-day dismissal cooldown via localStorage.
 * - Exposes `promptInstall()` to trigger the native install dialog and
 *   `dismiss()` to start the cooldown.
 */
export function useInstallPrompt(): UseInstallPromptReturn {
  const [deferredPrompt, setDeferredPrompt] =
    useState<BeforeInstallPromptEvent | null>(null);
  const [isInstalled, setIsInstalled] = useState(() =>
    typeof window !== "undefined"
      ? window.matchMedia("(display-mode: standalone)").matches
      : false,
  );
  const [dismissedAt, setDismissedAt] = useState<number | null>(() => {
    if (typeof window === "undefined") return null;
    const raw = localStorage.getItem(DISMISSED_AT_KEY);
    return raw ? Number(raw) : null;
  });

  // Keep a ref to the latest deferredPrompt so the event listener closure
  // can safely read it without going stale.
  const promptRef = useRef(deferredPrompt);
  useEffect(() => {
    promptRef.current = deferredPrompt;
  }, [deferredPrompt]);

  // ----- beforeinstallprompt listener -----
  useEffect(() => {
    if (typeof window === "undefined") return undefined;

    const handler = (e: Event) => {
      e.preventDefault();
      setDeferredPrompt(e as BeforeInstallPromptEvent);
    };

    window.addEventListener("beforeinstallprompt", handler);
    return () => window.removeEventListener("beforeinstallprompt", handler);
  }, []);

  // ----- appinstalled listener -----
  useEffect(() => {
    if (typeof window === "undefined") return undefined;

    const handler = () => {
      setIsInstalled(true);
      setDeferredPrompt(null);
    };

    window.addEventListener("appinstalled", handler);
    return () => window.removeEventListener("appinstalled", handler);
  }, []);

  // ----- display-mode standalone listener -----
  useEffect(() => {
    if (typeof window === "undefined") return undefined;

    const mql = window.matchMedia("(display-mode: standalone)");
    const handler = (e: MediaQueryListEvent) => setIsInstalled(e.matches);
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, []);

  // ----- Computed: canInstall -----
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => { setNow(Date.now()); }, [dismissedAt, deferredPrompt]);
  const inCooldown =
    dismissedAt !== null && now - dismissedAt < COOLDOWN_MS;
  const canInstall = deferredPrompt !== null && !isInstalled && !inCooldown;

  // ----- Actions -----
  const promptInstall = useCallback(async (): Promise<boolean> => {
    const prompt = promptRef.current;
    if (!prompt) return false;

    try {
      // BeforeInstallPromptEvent is not in standard TS lib types.
      // Cast to any to access the proprietary `prompt()` method.
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      await (prompt as any).prompt();
      // After prompting, clear the deferred event — the browser will fire
      // `appinstalled` if the user accepted.
      setDeferredPrompt(null);
      return true;
    } catch {
      return false;
    }
  }, []);

  const dismiss = useCallback(() => {
    const now = Date.now();
    setDismissedAt(now);
    try {
      localStorage.setItem(DISMISSED_AT_KEY, String(now));
    } catch {
      // Ignore storage errors (private browsing quota, etc.)
    }
  }, []);

  return { canInstall, isInstalled, promptInstall, dismiss };
}

/**
 * Minimal type for the non-standard BeforeInstallPromptEvent.
 * The real event has `platforms`, `userChoice`, and `prompt()`.
 */
interface BeforeInstallPromptEvent extends Event {
  readonly platforms: string[];
  readonly userChoice: Promise<{ outcome: "accepted" | "dismissed"; platform: string }>;
  prompt(): Promise<void>;
}
