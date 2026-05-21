import {
  RadarChart as RechartsRadar,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Radar,
  ResponsiveContainer,
  Tooltip,
} from "recharts";
import { useTranslation } from "react-i18next";
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
        M-Elo: {Math.round(point.value)}
      </p>
    </div>
  );
}

export function RadarChart({ data }: RadarChartProps) {
  const { t } = useTranslation("training");

  if (data.length === 0) {
    return (
      <div className="rounded-xl border border-border bg-card p-5">
        <h3 className="mb-4 text-sm font-semibold text-foreground">{t("radar.title")}</h3>
        <div className="flex h-[300px] items-center justify-center text-sm text-muted-foreground">
          {t("radar.empty")}
        </div>
      </div>
    );
  }

  const maxValue = Math.max(...data.map((d) => d.value), 0.1);
  const fullMark = Math.max(2000, maxValue * 1.2);

  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <h3 className="mb-4 text-sm font-semibold text-foreground">{t("radar.title")}</h3>
      <ResponsiveContainer width="100%" height={300}>
        <RechartsRadar cx="50%" cy="50%" outerRadius="70%" data={data}>
          <PolarGrid stroke="rgba(255,255,255,0.08)" />
          <PolarAngleAxis
            dataKey="topic"
            tick={{ fontSize: 11, fill: "rgba(255,255,255,0.6)" }}
          />
          <PolarRadiusAxis
            angle={90}
            domain={[800, fullMark]}
            tick={{ fontSize: 9, fill: "rgba(255,255,255,0.4)" }}
            axisLine={false}
          />
          <Tooltip content={<CustomTooltip />} />
          <Radar
            name="M-Elo"
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
