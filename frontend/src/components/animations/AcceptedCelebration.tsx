import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { usePrefersReducedMotion } from "@/hooks/useAnimation";

interface AcceptedCelebrationProps {
  /** Whether to show the celebration. */
  active: boolean;
  /** Optional callback when animation completes. */
  onComplete?: () => void;
  /** Duration in ms before auto-dismiss. Default 3000. */
  duration?: number;
  /** Optional class name for the overlay. */
  className?: string;
}

interface Particle {
  id: number;
  x: number;
  y: number;
  color: string;
  size: number;
  angle: number;
  speed: number;
}

const PARTICLE_COLORS = [
  "#00CC00",
  "#66FF66",
  "#FFD700",
  "#FFA500",
  "#00BFFF",
  "#FF69B4",
  "#ADFF2F",
];

function createParticles(count: number): Particle[] {
  return Array.from({ length: count }, (_, i) => ({
    id: i,
    x: 0,
    y: 0,
    color: PARTICLE_COLORS[i % PARTICLE_COLORS.length],
    size: Math.random() * 6 + 4,
    angle: (Math.PI * 2 * i) / count + (Math.random() - 0.5) * 0.5,
    speed: Math.random() * 200 + 100,
  }));
}

/**
 * "Accepted!" celebration overlay with particle burst effect.
 * Respects prefers-reduced-motion (shows text without particles).
 */
export function AcceptedCelebration({
  active,
  onComplete,
  duration = 3000,
  className = "",
}: AcceptedCelebrationProps) {
  const reduced = usePrefersReducedMotion();
  const [particles, setParticles] = useState<Particle[]>([]);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const idCounter = useRef(0);

  const particleCount = reduced ? 0 : 30;

  useEffect(() => {
    if (active && !reduced) {
      idCounter.current += 1;
      setParticles(createParticles(particleCount));
    } else if (active && reduced) {
      setParticles([]);
    }
    if (active) {
      timerRef.current = setTimeout(() => {
        onComplete?.();
      }, duration);
    }
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [active, reduced, particleCount, onComplete, duration]);

  const handleComplete = useCallback(() => {
    // Auto-cleanup after exit animation
  }, []);

  const particleElements = useMemo(
    () =>
      particles.map((p) => (
        <motion.div
          key={`${idCounter.current}-${p.id}`}
          initial={{ x: 0, y: 0, opacity: 1, scale: 1 }}
          animate={{
            x: Math.cos(p.angle) * p.speed,
            y: Math.sin(p.angle) * p.speed - 80,
            opacity: 0,
            scale: 0.2,
          }}
          transition={{
            duration: 1.5,
            ease: "easeOut",
          }}
          onAnimationComplete={p.id === 0 ? handleComplete : undefined}
          className="absolute rounded-full"
          style={{
            width: p.size,
            height: p.size,
            backgroundColor: p.color,
          }}
        />
      )),
    [particles, handleComplete],
  );

  return (
    <AnimatePresence>
      {active && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: reduced ? 0 : 0.3 }}
          className={`pointer-events-none fixed inset-0 z-50 flex items-center justify-center ${className}`}
        >
          {/* Particles */}
          <div className="absolute inset-0 flex items-center justify-center">
            {particleElements}
          </div>

          {/* Green flash background */}
          {!reduced && (
            <motion.div
              initial={{ opacity: 0.6 }}
              animate={{ opacity: 0 }}
              transition={{ duration: 0.8 }}
              className="absolute inset-0 bg-green-500/10"
            />
          )}

          {/* "Accepted!" text */}
          <motion.div
            initial={reduced ? { opacity: 0 } : { opacity: 0, scale: 0.3, y: 20 }}
            animate={
              reduced
                ? { opacity: 1 }
                : {
                    opacity: 1,
                    scale: [0.3, 1.2, 1],
                    y: 0,
                  }
            }
            exit={{ opacity: 0, scale: 0.8 }}
            transition={
              reduced
                ? { duration: 0 }
                : {
                    duration: 0.6,
                    ease: "easeOut",
                    times: [0, 0.5, 1],
                  }
            }
            className="relative z-10"
          >
            <h2
              className="text-5xl font-black tracking-wider sm:text-7xl"
              style={{
                color: "#00CC00",
                textShadow: reduced
                  ? "none"
                  : "0 0 20px rgba(0, 204, 0, 0.5), 0 0 40px rgba(0, 204, 0, 0.3)",
              }}
            >
              Accepted!
            </h2>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
