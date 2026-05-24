/**
 * Training page skill radar chart (FR-25.1).
 *
 * Displays 8-dimension radar chart below the training page header.
 * Each dimension is clickable and navigates to the corresponding topic.
 */

import { useNavigate } from "react-router-dom";
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
import { useTheme } from "@/hooks/useTheme";
import type { RadarDataPoint, TopicInfo } from "@/types";
import { RADAR_DIMENSIONS, cfTagToDimensionKey } from "@/utils/radar";

interface TrainingRadarChartProps {
  data: RadarDataPoint[];
  topics: TopicInfo[];
}

// ---------------------------------------------------------------------------
// Click handler: map radar dimension key -> topicId for navigation
// ---------------------------------------------------------------------------

function buildDimensionToTopicMap(
  topics: TopicInfo[],
): Map<string, string> {
  const map = new Map<string, string>();
  for (const topic of topics) {
    for (const tag of topic.cf_tags) {
      const dimKey = cfTagToDimensionKey(tag);
      if (dimKey) {
        map.set(dimKey, topic.id);
      }
    }
  }
  return map;
}

// ---------------------------------------------------------------------------
// Custom tooltip
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Custom angle tick (clickable)
// ---------------------------------------------------------------------------

interface ClickableTickProps {
  x?: number;
  y?: number;
  payload?: { value: string; index: number };
  dimToTopicId: Map<string, string>;
  onNavigate: (topicId: string | undefined) => void;
}

function ClickableTick({
  x = 0,
  y = 0,
  payload,
  dimToTopicId,
  onNavigate,
}: ClickableTickProps) {
  if (!payload) return null;

  const dim = RADAR_DIMENSIONS[payload.index];
  const topicId = dim ? dimToTopicId.get(dim.key) : undefined;
  const isClickable = !!topicId;

  return (
    <g
      className={isClickable ? "cursor-pointer" : ""}
      onClick={() => onNavigate(topicId)}
    >
      <text
        x={x}
        y={y}
        textAnchor="middle"
        dominantBaseline="central"
        fill="currentColor"
        className={
          isClickable
            ? "fill-muted-foreground text-[11px] font-medium hover:fill-primary transition-colors"
            : "fill-muted-foreground text-[11px]"
        }
        style={{ pointerEvents: isClickable ? "all" : "none" }}
      >
        {payload.value}
      </text>
    </g>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function TrainingRadarChart({ data, topics }: TrainingRadarChartProps) {
  const { t } = useTranslation("training");
  const { resolved } = useTheme();
  const navigate = useNavigate();

  const isDark = resolved === "dark";
  const gridStroke = isDark ? "rgba(255,255,255,0.08)" : "rgba(0,0,0,0.08)";
  const radiusTickFill = isDark ? "rgba(255,255,255,0.4)" : "rgba(0,0,0,0.35)";

  const dimToTopicId = buildDimensionToTopicMap(topics);

  const handleNavigate = (topicId: string | undefined) => {
    if (topicId) {
      navigate(`/training/${topicId}`);
    }
  };

  if (data.length === 0) {
    return (
      <div className="rounded-xl border border-border bg-card p-5">
        <h3 className="mb-4 text-sm font-semibold text-foreground">
          {t("radar.title")}
        </h3>
        <div className="flex h-[280px] items-center justify-center text-sm text-muted-foreground">
          {t("radar.empty")}
        </div>
      </div>
    );
  }

  const maxValue = Math.max(...data.map((d) => d.value), 0.1);
  const fullMark = Math.max(2000, maxValue * 1.2);

  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <h3 className="mb-4 text-sm font-semibold text-foreground">
        {t("radar.title")}
      </h3>
      <ResponsiveContainer width="100%" height={280}>
        <RechartsRadar cx="50%" cy="50%" outerRadius="70%" data={data}>
          <PolarGrid stroke={gridStroke} />
          <PolarAngleAxis
            dataKey="topic"
            tick={
              <ClickableTick
                dimToTopicId={dimToTopicId}
                onNavigate={handleNavigate}
              />
            }
          />
          <PolarRadiusAxis
            angle={90}
            domain={[800, fullMark]}
            tick={{ fontSize: 9, fill: radiusTickFill }}
            axisLine={false}
          />
          <Tooltip content={<CustomTooltip />} />
          <Radar
            name="M-Elo"
            dataKey="value"
            stroke="#22c55e"
            fill="#22c55e"
            fillOpacity={0.15}
            strokeWidth={2}
          />
        </RechartsRadar>
      </ResponsiveContainer>
    </div>
  );
}
