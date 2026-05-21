/**
 * Achievement popup component -- "gacha pull" style full-screen overlay.
 *
 * Shows a gold-bordered card that scales in with a bounce effect when
 * achievement events are received from the backend.  Respects
 * prefers-reduced-motion.
 */

import { useEffect, useRef, useState, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Zap, Trophy, Star } from "lucide-react";
import { usePrefersReducedMotion } from "@/hooks/useAnimation";

interface Achievement {
  type: string;
  title: string;
  description: string;
  icon: string;
}

interface AchievementPopupProps {
  /** List of achievements to display. */
  achievements: Achievement[];
  /** Callback when all achievements have been dismissed. */
  onComplete?: () => void;
  /** Duration per achievement card in ms. Default 3500. */
  duration?: number;
}

/** Map icon name strings to Lucide components. */
const ICON_MAP: Record<string, React.ComponentType<{ className?: string }>> = {
  zap: Zap,
  trophy: Trophy,
  star: Star,
};

/** Color theme per achievement type. */
const TYPE_COLORS: Record<string, { border: string; glow: string; bg: string }> = {
  overkill_bonus: {
    border: "border-yellow-500/60",
    glow: "rgba(234, 179, 8, 0.3)",
    bg: "from-yellow-500/10 via-amber-500/10 to-yellow-500/10",
  },
  contest_win: {
    border: "border-purple-500/60",
    glow: "rgba(168, 85, 247, 0.3)",
    bg: "from-purple-500/10 via-fuchsia-500/10 to-purple-500/10",
  },
  personal_best_pp: {
    border: "border-blue-500/60",
    glow: "rgba(59, 130, 246, 0.3)",
    bg: "from-blue-500/10 via-cyan-500/10 to-blue-500/10",
  },
};

const DEFAULT_COLORS = TYPE_COLORS.overkill_bonus;

/**
 * Full-screen achievement popup with gacha-pull style animation.
 * Shows each achievement sequentially with scale-bounce entrance,
 * gold/purple/blue border glow, and fade-out exit.
 */
export function AchievementPopup({
  achievements,
  onComplete,
  duration = 3500,
}: AchievementPopupProps) {
  const reduced = usePrefersReducedMotion();
  const [currentIndex, setCurrentIndex] = useState(0);
  const [visible, setVisible] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const hasAchievements = achievements.length > 0;
  const current = hasAchievements ? achievements[currentIndex] : null;

  const advance = useCallback(() => {
    setVisible(false);
    // Wait for exit animation, then advance
    setTimeout(() => {
      const next = currentIndex + 1;
      if (next < achievements.length) {
        setCurrentIndex(next);
        setVisible(true);
      } else {
        onComplete?.();
      }
    }, reduced ? 0 : 400);
  }, [currentIndex, achievements.length, onComplete, reduced]);

  useEffect(() => {
    if (hasAchievements) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- reset popup state on achievement list change
      setCurrentIndex(0);
      setVisible(true);
    }
  }, [hasAchievements, achievements]);

  useEffect(() => {
    if (visible) {
      timerRef.current = setTimeout(advance, duration);
    }
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [visible, advance, duration]);

  if (!current) return null;

  const colors = TYPE_COLORS[current.type] ?? DEFAULT_COLORS;
  const IconComponent = ICON_MAP[current.icon] ?? Star;

  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: reduced ? 0 : 0.3 }}
          className="pointer-events-auto fixed inset-0 z-[60] flex items-center justify-center bg-black/40 backdrop-blur-sm"
        >
          {/* Achievement card */}
          <motion.div
            initial={reduced ? { opacity: 0 } : { opacity: 0, scale: 0.3, y: 40 }}
            animate={
              reduced
                ? { opacity: 1 }
                : {
                    opacity: 1,
                    scale: [0.3, 1.15, 1],
                    y: 0,
                  }
            }
            exit={reduced ? { opacity: 0 } : { opacity: 0, scale: 0.8, y: -20 }}
            transition={
              reduced
                ? { duration: 0 }
                : {
                    duration: 0.5,
                    ease: "easeOut",
                    times: [0, 0.6, 1],
                  }
            }
            className={`relative max-w-sm overflow-hidden rounded-2xl border-2 ${colors.border} bg-gradient-to-br ${colors.bg} p-8 shadow-2xl`}
            style={{
              boxShadow: reduced ? "none" : `0 0 60px ${colors.glow}, 0 0 120px ${colors.glow}`,
            }}
          >
            {/* Radial glow behind icon */}
            {!reduced && (
              <div
                className="pointer-events-none absolute inset-0 opacity-20"
                style={{
                  background: `radial-gradient(circle at 50% 30%, ${colors.glow}, transparent 60%)`,
                }}
              />
            )}

            <div className="relative flex flex-col items-center gap-4 text-center">
              {/* Icon */}
              <motion.div
                initial={reduced ? {} : { rotate: -15 }}
                animate={reduced ? {} : { rotate: 0 }}
                transition={{ duration: 0.4, type: "spring", stiffness: 200 }}
                className={`flex size-16 items-center justify-center rounded-2xl ${colors.border} border bg-black/30`}
              >
                <IconComponent className="size-8 text-yellow-400" />
              </motion.div>

              {/* Title */}
              <h2 className="text-2xl font-black tracking-wide text-foreground">
                {current.title}
              </h2>

              {/* Description */}
              <p className="text-sm leading-relaxed text-muted-foreground">
                {current.description}
              </p>
            </div>

            {/* Shimmer overlay */}
            {!reduced && (
              <motion.div
                initial={{ x: "-100%", opacity: 0.5 }}
                animate={{ x: "200%", opacity: 0 }}
                transition={{ duration: 1.5, delay: 0.3, ease: "easeInOut" }}
                className="pointer-events-none absolute inset-0 w-1/3 bg-gradient-to-r from-transparent via-white/10 to-transparent"
              />
            )}
          </motion.div>

          {/* Progress dots */}
          {achievements.length > 1 && (
            <div className="absolute bottom-8 flex gap-2">
              {achievements.map((_, i) => (
                <div
                  key={i}
                  className={`size-2 rounded-full transition-colors ${
                    i === currentIndex ? "bg-yellow-400" : "bg-white/30"
                  }`}
                />
              ))}
            </div>
          )}
        </motion.div>
      )}
    </AnimatePresence>
  );
}
