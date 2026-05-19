import { motion, AnimatePresence } from "framer-motion";
import { usePrefersReducedMotion } from "@/hooks/useAnimation";

interface LevelUpEffectProps {
  /** Whether the level-up effect should show. */
  active: boolean;
  /** New rank/level label to display. */
  label?: string;
  /** Color for the effect (defaults to gold). */
  color?: string;
  /** Optional class name. */
  className?: string;
}

/**
 * Level-up / rank change effect with burst animation.
 * Shows the new rank label with a radial glow burst.
 * Respects prefers-reduced-motion.
 */
export function LevelUpEffect({
  active,
  label,
  color = "#FFD700",
  className = "",
}: LevelUpEffectProps) {
  const reduced = usePrefersReducedMotion();

  return (
    <AnimatePresence>
      {active && (
        <motion.div
          initial={
            reduced
              ? { opacity: 0 }
              : { opacity: 0, scale: 0.3, rotate: -10 }
          }
          animate={
            reduced
              ? { opacity: 1 }
              : {
                  opacity: 1,
                  scale: [0.3, 1.2, 1],
                  rotate: 0,
                }
          }
          exit={{ opacity: 0, scale: 0.8 }}
          transition={
            reduced
              ? { duration: 0 }
              : {
                  duration: 0.8,
                  ease: "easeOut",
                  times: [0, 0.6, 1],
                }
          }
          className={`relative flex flex-col items-center gap-2 ${className}`}
        >
          {/* Glow background */}
          {!reduced && (
            <motion.div
              initial={{ scale: 0, opacity: 0.8 }}
              animate={{ scale: 3, opacity: 0 }}
              transition={{ duration: 1.2, ease: "easeOut" }}
              className="absolute size-16 rounded-full"
              style={{ backgroundColor: color, filter: "blur(20px)" }}
            />
          )}

          {/* Icon */}
          <div
            className="relative flex size-16 items-center justify-center rounded-full"
            style={{
              background: `radial-gradient(circle, ${color}40, transparent)`,
              border: `2px solid ${color}60`,
            }}
          >
            <svg
              width="32"
              height="32"
              viewBox="0 0 24 24"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
            >
              <path
                d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z"
                fill={color}
                stroke={color}
                strokeWidth="1"
              />
            </svg>
          </div>

          {/* Label */}
          {label && (
            <motion.span
              initial={reduced ? false : { opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: reduced ? 0 : 0.3, duration: reduced ? 0 : 0.4 }}
              className="text-lg font-bold"
              style={{ color }}
            >
              {label}
            </motion.span>
          )}
        </motion.div>
      )}
    </AnimatePresence>
  );
}
