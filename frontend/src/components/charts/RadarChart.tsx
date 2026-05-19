import {
  RadarChart as RechartsRadar,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Radar,
  ResponsiveContainer,
  Tooltip,
} from "recharts";
import type { RadarDataPoint } from "@/types";

interface RadarChartProps {
  data: RadarDataPoint[];
}

function CustomTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ value: number; payload: RadarDataPoint }>;
}) {
  if (!active || !payload?.length) return null;
  const point = payload[0].payload;
  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2 shadow-lg">
      <p className="text-sm font-semibold text-foreground">{point.topic}</p>
      <p className="text-xs text-muted-foreground">
        Completion: {point.value.toFixed(1)}%
      </p>
    </div>
  );
}

export function RadarChart({ data }: RadarChartProps) {
  if (data.length === 0) {
    return (
      <div className="rounded-xl border border-border bg-card p-5">
        <h3 className="mb-4 text-sm font-semibold text-foreground">Skill Radar</h3>
        <div className="flex h-[300px] items-center justify-center text-sm text-muted-foreground">
          No training data yet. Start training to see your skill profile!
        </div>
      </div>
    );
  }

  const maxValue = Math.max(...data.map((d) => d.value), 0.1);
  const fullMark = Math.max(maxValue * 1.3, maxValue + 0.1);

  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <h3 className="mb-4 text-sm font-semibold text-foreground">Skill Radar</h3>
      <ResponsiveContainer width="100%" height={300}>
        <RechartsRadar cx="50%" cy="50%" outerRadius="70%" data={data}>
          <PolarGrid stroke="rgba(255,255,255,0.08)" />
          <PolarAngleAxis
            dataKey="topic"
            tick={{ fontSize: 11, fill: "rgba(255,255,255,0.6)" }}
          />
          <PolarRadiusAxis
            angle={90}
            domain={[0, fullMark]}
            tick={{ fontSize: 9, fill: "rgba(255,255,255,0.4)" }}
            axisLine={false}
          />
          <Tooltip content={<CustomTooltip />} />
          <Radar
            name="Completion"
            dataKey="value"
            stroke="#6366f1"
            fill="#6366f1"
            fillOpacity={0.2}
            strokeWidth={2}
          />
        </RechartsRadar>
      </ResponsiveContainer>
    </div>
  );
}
