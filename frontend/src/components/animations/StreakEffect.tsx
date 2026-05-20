import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { usePrefersReducedMotion } from "@/hooks/useAnimation";

interface StreakEffectProps {
  /** Current streak count. */
  streak: number;
  /** Optional class name for positioning. */
  className?: string;
}

/**
 * Streak counter with escalation effects.
 * - Shows flame icon + streak count (including 0).
 * - Increasing visual intensity at higher streaks.
 * - Screen edge glow at higher streaks.
 * - Flame icon is grey when streak is 0.
 * - Respects prefers-reduced-motion.
 */

/** Inline SVG flame icon. */
function FlameIcon({ color }: { color: string }) {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="currentColor"
      style={{ color }}
    >
      <path d="M12 23c-3.866 0-7-2.686-7-6 0-2.418 1.272-4.336 2.38-5.843a1 1 0 0 1 1.74.265C9.674 12.91 10.664 14 12 14c-1.05-1.5-.5-3.5.5-5 1-1.5 2-2.5 2-4.5 0-.5-.1-1-.3-1.5a1 1 0 0 1 1.3-1.2C18.7 3.3 22 7.3 22 11.5 22 19 17 23 12 23z" />
    </svg>
  );
}

export function StreakEffect({ streak, className = "" }: StreakEffectProps) {
  const [prevStreak, setPrevStreak] = useState(0);
  const [pulsing, setPulsing] = useState(false);
  const reduced = usePrefersReducedMotion();

  useEffect(() => {
    if (streak > prevStreak && streak >= 2) {
      setPulsing(true);
      const t = setTimeout(() => setPulsing(false), 600);
      return () => clearTimeout(t);
    }
    setPrevStreak(streak);
  }, [streak, prevStreak]);

  const intensity = Math.min(streak, 6);
  const glowColor =
    intensity <= 2
      ? "rgba(255, 187, 0, 0.3)"
      : intensity <= 4
        ? "rgba(255, 140, 0, 0.4)"
        : "rgba(255, 60, 0, 0.5)";

  return (
    <>
      {!reduced && pulsing && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.6 }}
          className="pointer-events-none fixed inset-0 z-40"
          style={{
            boxShadow: `inset 0 0 ${40 * intensity}px ${10 * intensity}px ${glowColor}`,
          }}
        />
      )}

      <AnimatePresence mode="wait">
        <motion.div
          key={streak}
          initial={reduced ? false : { scale: 0.5, opacity: 0 }}
          animate={{
            scale: pulsing && !reduced ? [1, 1.3, 1] : 1,
            opacity: 1,
          }}
          exit={reduced ? { opacity: 0 } : { scale: 0.5, opacity: 0 }}
          transition={
            reduced
              ? { duration: 0 }
              : {
                  scale: { duration: 0.4, ease: "easeInOut" },
                  opacity: { duration: 0.2 },
                }
          }
          className={`flex items-center justify-center gap-1 ${className}`}
        >
          <FlameIcon
            color={
              streak < 2
                ? "#888"
                : intensity <= 2
                  ? "#FFBB00"
                  : intensity <= 4
                    ? "#FF8C00"
                    : "#FF3C00"
            }
          />
          <span
            className="text-xl font-black tabular-nums"
            style={{
              color:
                streak < 2
                  ? "#888"
                  : intensity <= 2
                    ? "#FFBB00"
                    : intensity <= 4
                      ? "#FF8C00"
                      : "#FF3C00",
              textShadow:
                intensity > 3 && !reduced
                  ? `0 0 ${intensity * 4}px ${glowColor}`
                  : "none",
            }}
          >
            {streak}
          </span>
        </motion.div>
      </AnimatePresence>
    </>
  );
}
