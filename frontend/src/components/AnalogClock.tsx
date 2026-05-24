import { useEffect, useState } from "react";

interface AnalogClockProps {
  /** Diameter in pixels. Defaults to 16 (matches Tailwind size-4). */
  size?: number;
}

/**
 * Lightweight SVG analog clock that shows the current system time.
 * Hands update once per second via `setInterval`.
 * Uses `currentColor` so it adapts to dark/light themes automatically.
 */
export function AnalogClock({ size = 16 }: AnalogClockProps) {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  const hours = now.getHours() % 12;
  const minutes = now.getMinutes();
  const seconds = now.getSeconds();

  // Angle calculations (0 = 12 o'clock, clockwise)
  const hourAngle = (hours + minutes / 60) * 30; // 360 / 12 = 30 deg per hour
  const minuteAngle = (minutes + seconds / 60) * 6; // 360 / 60 = 6 deg per minute
  const secondAngle = seconds * 6;

  // Hand coordinates (clock face centered at 50,50 with radius 46)
  const cx = 50;
  const cy = 50;
  const r = 46;

  const handEnd = (angle: number, length: number) => ({
    x2: cx + length * Math.sin((angle * Math.PI) / 180),
    y2: cy - length * Math.cos((angle * Math.PI) / 180),
  });

  const hour = handEnd(hourAngle, r * 0.5);
  const minute = handEnd(minuteAngle, r * 0.7);
  const second = handEnd(secondAngle, r * 0.82);

  // 12 hour tick marks
  const ticks = Array.from({ length: 12 }, (_, i) => {
    const a = (i * 30 * Math.PI) / 180;
    const outerR = r;
    const innerR = i % 3 === 0 ? r - 8 : r - 5;
    return {
      x1: cx + innerR * Math.sin(a),
      y1: cy - innerR * Math.cos(a),
      x2: cx + outerR * Math.sin(a),
      y2: cy - outerR * Math.cos(a),
      major: i % 3 === 0,
    };
  });

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 100 100"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className="shrink-0"
      aria-hidden="true"
    >
      {/* Clock face outline */}
      <circle
        cx={cx}
        cy={cy}
        r={r + 2}
        stroke="currentColor"
        strokeWidth={3}
        opacity={0.25}
      />

      {/* Hour tick marks */}
      {ticks.map((t, i) => (
        <line
          key={i}
          x1={t.x1}
          y1={t.y1}
          x2={t.x2}
          y2={t.y2}
          stroke="currentColor"
          strokeWidth={t.major ? 3 : 1.5}
          strokeLinecap="round"
          opacity={t.major ? 0.7 : 0.4}
        />
      ))}

      {/* Hour hand */}
      <line
        x1={cx}
        y1={cy}
        {...hour}
        stroke="currentColor"
        strokeWidth={4}
        strokeLinecap="round"
        opacity={0.85}
      />

      {/* Minute hand */}
      <line
        x1={cx}
        y1={cy}
        {...minute}
        stroke="currentColor"
        strokeWidth={2.5}
        strokeLinecap="round"
        opacity={0.75}
      />

      {/* Second hand */}
      <line
        x1={cx}
        y1={cy}
        {...second}
        stroke="currentColor"
        strokeWidth={1.2}
        strokeLinecap="round"
        opacity={0.55}
      />

      {/* Center dot */}
      <circle cx={cx} cy={cy} r={2.5} fill="currentColor" opacity={0.7} />
    </svg>
  );
}
