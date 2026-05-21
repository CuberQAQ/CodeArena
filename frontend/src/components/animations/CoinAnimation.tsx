import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { usePrefersReducedMotion } from "@/hooks/useAnimation";

interface CoinAnimationProps {
  /** Number of tokens earned. Triggers animation when changed. */
  amount: number;
  /** Unique key to re-trigger animation. */
  triggerKey?: string | number;
  /** Optional class name for the container. */
  className?: string;
}

/**
 * Token/coin earning animation.
 * Shows a coin icon that flies upward and fades, with a counting number.
 * Respects prefers-reduced-motion.
 */
export function CoinAnimation({ amount, triggerKey, className = "" }: CoinAnimationProps) {
  const [visible, setVisible] = useState(false);
  const [displayAmount, setDisplayAmount] = useState(0);
  const reduced = usePrefersReducedMotion();
  const prevAmountRef = useRef(0);

  useEffect(() => {
    if (amount <= 0 || amount === prevAmountRef.current) return;
    prevAmountRef.current = amount;
    setVisible(true);
    setDisplayAmount(0);

    if (reduced) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- reduced-motion: show amount immediately
      setDisplayAmount(amount);
      const t = setTimeout(() => setVisible(false), 1500);
      return () => clearTimeout(t);
    }

    const duration = 600;
    const startTime = performance.now();
    let raf: number;

    const animate = (now: number) => {
      const progress = Math.min((now - startTime) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      setDisplayAmount(Math.round(amount * eased));
      if (progress < 1) {
        raf = requestAnimationFrame(animate);
      }
    };
    raf = requestAnimationFrame(animate);

    const hideTimer = setTimeout(() => setVisible(false), 2000);
    return () => {
      cancelAnimationFrame(raf);
      clearTimeout(hideTimer);
    };
  }, [amount, triggerKey, reduced]);

  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          key={triggerKey ?? "coin"}
          initial={reduced ? false : { opacity: 0, y: 0, scale: 0.5 }}
          animate={{ opacity: 1, y: -20, scale: 1 }}
          exit={{ opacity: 0, y: -40 }}
          transition={
            reduced
              ? { duration: 0 }
              : {
                  duration: 1.5,
                  ease: "easeOut",
                }
          }
          className={`pointer-events-none flex items-center gap-1.5 ${className}`}
        >
          {/* Coin icon */}
          <svg
            width="20"
            height="20"
            viewBox="0 0 24 24"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
          >
            <circle cx="12" cy="12" r="10" fill="#FFD700" stroke="#DAA520" strokeWidth="1.5" />
            <text
              x="12"
              y="16"
              textAnchor="middle"
              fontSize="12"
              fontWeight="bold"
              fill="#B8860B"
            >
              $
            </text>
          </svg>
          <span className="text-lg font-bold text-yellow-400 tabular-nums">
            +{displayAmount}
          </span>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
