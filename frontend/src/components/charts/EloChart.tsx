import { useState, useMemo } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import type { EloHistoryPoint } from "@/types";

interface EloChartProps {
  data: EloHistoryPoint[];
}

type TimeRange = "7d" | "30d" | "all";

function filterByRange(points: EloHistoryPoint[], range: TimeRange): EloHistoryPoint[] {
  if (range === "all" || points.length === 0) return points;

  const now = Date.now();
  const cutoff = range === "7d" ? now - 7 * 86_400_000 : now - 30 * 86_400_000;

  return points.filter((p) => new Date(p.date).getTime() >= cutoff);
}

function formatDateLabel(dateStr: string): string {
  const d = new Date(dateStr);
  return `${(d.getMonth() + 1).toString().padStart(2, "0")}/${d.getDate().toString().padStart(2, "0")}`;
}

function CustomTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: Array<{ value: number; payload: EloHistoryPoint }>;
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  const point = payload[0].payload;
  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2 shadow-lg">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-sm font-semibold text-foreground">Elo: {point.elo}</p>
      <p className={`text-xs font-medium ${point.change >= 0 ? "text-green-400" : "text-red-400"}`}>
        {point.change >= 0 ? "+" : ""}
        {point.change}
      </p>
    </div>
  );
}

const RANGE_OPTIONS: { value: TimeRange; label: string }[] = [
  { value: "7d", label: "7D" },
  { value: "30d", label: "30D" },
  { value: "all", label: "All" },
];

export function EloChart({ data }: EloChartProps) {
  const [range, setRange] = useState<TimeRange>("30d");

  const filtered = useMemo(() => filterByRange(data, range), [data, range]);

  const eloDomain = useMemo(() => {
    if (filtered.length === 0) return { min: 800, max: 1200 };
    const elos = filtered.map((p) => p.elo);
    const min = Math.min(...elos);
    const max = Math.max(...elos);
    const padding = Math.max(Math.ceil((max - min) * 0.15), 20);
    return { min: min - padding, max: max + padding };
  }, [filtered]);

  if (data.length === 0) {
    return (
      <div className="rounded-xl border border-border bg-card p-5">
        <h3 className="mb-4 text-sm font-semibold text-foreground">Elo Trend</h3>
        <div className="flex h-[220px] items-center justify-center text-sm text-muted-foreground">
          No Elo history yet. Start playing to see your progress!
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-foreground">Elo Trend</h3>
        <div className="flex gap-1 rounded-lg bg-muted p-0.5">
          {RANGE_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => setRange(opt.value)}
              className={`rounded-md px-2 py-1 text-xs font-medium transition-colors ${
                range === opt.value
                  ? "bg-card text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>
      <ResponsiveContainer width="100%" height={220}>
        <LineChart data={filtered} margin={{ top: 5, right: 5, bottom: 5, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
          <XAxis
            dataKey="date"
            tickFormatter={formatDateLabel}
            tick={{ fontSize: 11, fill: "rgba(255,255,255,0.5)" }}
            axisLine={{ stroke: "rgba(255,255,255,0.1)" }}
            tickLine={false}
          />
          <YAxis
            domain={[eloDomain.min, eloDomain.max]}
            tick={{ fontSize: 11, fill: "rgba(255,255,255,0.5)" }}
            axisLine={{ stroke: "rgba(255,255,255,0.1)" }}
            tickLine={false}
            width={40}
          />
          <Tooltip content={<CustomTooltip />} />
          <Line
            type="monotone"
            dataKey="elo"
            stroke="#6366f1"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, stroke: "#6366f1", fill: "#1a1a2e", strokeWidth: 2 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
