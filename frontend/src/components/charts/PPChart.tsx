import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import type { PPContributionItem } from "@/types";
import { getRatingColor } from "@/utils";

interface PPChartProps {
  data: PPContributionItem[];
}

function CustomTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ value: number; payload: PPContributionItem }>;
}) {
  if (!active || !payload?.length) return null;
  const item = payload[0].payload;
  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2 shadow-lg">
      <p className="text-sm font-semibold text-foreground">{item.problem_name}</p>
      <p className="text-xs text-muted-foreground">
        Rating: {item.rating} | PP: {item.pp.toFixed(1)}
      </p>
    </div>
  );
}

export function PPChart({ data }: PPChartProps) {
  if (data.length === 0) {
    return (
      <div className="rounded-xl border border-border bg-card p-5">
        <h3 className="mb-4 text-sm font-semibold text-foreground">Top PP Contributions</h3>
        <div className="flex h-[220px] items-center justify-center text-sm text-muted-foreground">
          No PP records yet. Solve problems to build your profile!
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <h3 className="mb-4 text-sm font-semibold text-foreground">Top PP Contributions</h3>
      <ResponsiveContainer width="100%" height={220}>
        <BarChart data={data} margin={{ top: 5, right: 5, bottom: 5, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" vertical={false} />
          <XAxis
            dataKey="problem_name"
            tick={{ fontSize: 9, fill: "rgba(255,255,255,0.5)" }}
            axisLine={{ stroke: "rgba(255,255,255,0.1)" }}
            tickLine={false}
            interval={0}
            angle={-35}
            textAnchor="end"
            height={50}
          />
          <YAxis
            tick={{ fontSize: 11, fill: "rgba(255,255,255,0.5)" }}
            axisLine={{ stroke: "rgba(255,255,255,0.1)" }}
            tickLine={false}
            width={35}
          />
          <Tooltip content={<CustomTooltip />} />
          <Bar dataKey="pp" radius={[3, 3, 0, 0]} maxBarSize={28}>
            {data.map((entry, index) => (
              <Cell key={index} fill={getRatingColor(entry.rating)} fillOpacity={0.85} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
