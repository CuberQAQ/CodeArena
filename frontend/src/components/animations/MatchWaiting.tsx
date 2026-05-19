import { motion } from "framer-motion";
import { Swords } from "lucide-react";
import { usePrefersReducedMotion } from "@/hooks/useAnimation";

interface MatchWaitingProps {
  /** Optional label text. Defaults to "Finding Opponent..." */
  label?: string;
  /** Optional class name. */
  className?: string;
}

/**
 * Matchmaking waiting animation with pulsing rings.
 * Respects prefers-reduced-motion.
 */
export function MatchWaiting({ label = "Finding Opponent...", className = "" }: MatchWaitingProps) {
  const reduced = usePrefersReducedMotion();

  return (
    <div className={`flex flex-col items-center gap-4 ${className}`}>
      {/* Pulse rings */}
      <div className="relative flex size-24 items-center justify-center">
        {/* Outer ring */}
        {!reduced && (
          <>
            <motion.div
              className="absolute inset-0 rounded-full border-2 border-primary/30"
              animate={{
                scale: [1, 1.5, 1],
                opacity: [0.5, 0, 0.5],
              }}
              transition={{
                duration: 2,
                repeat: Infinity,
                ease: "easeInOut",
              }}
            />
            <motion.div
              className="absolute inset-0 rounded-full border-2 border-primary/20"
              animate={{
                scale: [1, 1.8, 1],
                opacity: [0.3, 0, 0.3],
              }}
              transition={{
                duration: 2,
                repeat: Infinity,
                ease: "easeInOut",
                delay: 0.4,
              }}
            />
            <motion.div
              className="absolute inset-0 rounded-full border border-primary/10"
              animate={{
                scale: [1, 2, 1],
                opacity: [0.2, 0, 0.2],
              }}
              transition={{
                duration: 2,
                repeat: Infinity,
                ease: "easeInOut",
                delay: 0.8,
              }}
            />
          </>
        )}

        {/* Center icon */}
        <motion.div
          className="relative z-10 flex size-16 items-center justify-center rounded-full bg-primary/10"
          animate={
            reduced
              ? {}
              : {
                  scale: [1, 1.1, 1],
                }
          }
          transition={{
            duration: 1.5,
            repeat: Infinity,
            ease: "easeInOut",
          }}
        >
          <Swords className="size-8 text-primary" />
        </motion.div>
      </div>

      {/* Label */}
      <motion.p
        className="text-sm font-medium text-muted-foreground"
        animate={
          reduced
            ? {}
            : {
                opacity: [0.5, 1, 0.5],
              }
        }
        transition={{
          duration: 2,
          repeat: Infinity,
          ease: "easeInOut",
        }}
      >
        {label}
      </motion.p>
    </div>
  );
}
