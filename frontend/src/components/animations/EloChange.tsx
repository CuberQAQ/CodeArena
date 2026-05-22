import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { usePrefersReducedMotion, useSpringTransition } from "@/hooks/useAnimation";

interface EloChangeProps {
  /** The Elo change value (positive = gain, negative = loss). */
  value: number | null | undefined;
  /** Trigger key -- change this to replay the animation. */
  triggerKey?: string | number;
  /** Optional class name for the container. */
  className?: string;
}

/**
 * Animated Elo change display.
 * - Positive values animate in green with a count-up effect.
 * - Negative values animate in red with a count-down effect.
 * - Respects prefers-reduced-motion.
 */
export function EloChange({ value, triggerKey, className = "" }: EloChangeProps) {
  const [displayValue, setDisplayValue] = useState(0);
  const [visible, setVisible] = useState(false);
  const reduced = usePrefersReducedMotion();
  const spring = useSpringTransition();

  useEffect(() => {
    if (value == null) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- hide animation when no value
      setVisible(false);
      return;
    }
    setVisible(true);
    setDisplayValue(0);

    if (reduced) {
      setDisplayValue(value);
      return;
    }

    const duration = 800;
    const startTime = performance.now();
    let raf: number;

    const animate = (now: number) => {
      const progress = Math.min((now - startTime) / duration, 1);
      // Ease-out cubic
      const eased = 1 - Math.pow(1 - progress, 3);
      setDisplayValue(Math.round(value * eased));
      if (progress < 1) {
        raf = requestAnimationFrame(animate);
      }
    };
    raf = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(raf);
  }, [value, triggerKey, reduced]);

  const isPositive = (value ?? 0) > 0;
  const isZero = (value ?? 0) === 0;
  const colorClass = isZero
    ? "text-muted-foreground"
    : isPositive
      ? "text-green-400"
      : "text-red-400";

  return (
    <AnimatePresence>
      {visible && value != null && (
        <motion.div
          key={triggerKey ?? "elo"}
          initial={reduced ? false : { opacity: 0, y: -10, scale: 0.8 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: -10 }}
          transition={spring}
          className={`text-2xl font-bold tabular-nums ${colorClass} ${className}`}
        >
          {isPositive ? "+" : ""}
          {displayValue}
        </motion.div>
      )}
    </AnimatePresence>
  );
}
