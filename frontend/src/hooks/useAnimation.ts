import { useEffect, useState } from "react";
import { useReducedMotion } from "framer-motion";

/**
 * Returns true if the user prefers reduced motion.
 * Combines framer-motion's detection with a manual check for robustness.
 */
export function usePrefersReducedMotion(): boolean {
  const framerReduced = useReducedMotion();
  const [manualCheck, setManualCheck] = useState(false);

  useEffect(() => {
    const mql = window.matchMedia("(prefers-reduced-motion: reduce)");
    setManualCheck(mql.matches);
    const handler = (e: MediaQueryListEvent) => setManualCheck(e.matches);
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, []);

  return framerReduced ?? manualCheck;
}

/**
 * Returns animation duration multiplier: 0 when reduced motion is preferred, 1 otherwise.
 */
export function useAnimationScale(): number {
  return usePrefersReducedMotion() ? 0 : 1;
}

/**
 * Hook that returns framer-motion transition presets adjusted for reduced-motion preference.
 */
export function useSpringTransition() {
  const reduced = usePrefersReducedMotion();
  return reduced
    ? { duration: 0 }
    : {
        type: "spring" as const,
        stiffness: 300,
        damping: 30,
      };
}

export function useTweenTransition(duration: number = 0.3) {
  const reduced = usePrefersReducedMotion();
  return reduced ? { duration: 0 } : { duration, ease: "easeOut" as const };
}
