import {
  Tooltip,
  ResponsiveContainer,
  Cell,
  PieChart,
  Pie,
} from "recharts";
import { TrendingUp, Swords, Coins, Target } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { DashboardStats, DifficultyDistribution } from "@/types";

interface StatsPanelProps {
  stats: DashboardStats;
}

function StatCard({
  icon: Icon,
  label,
  value,
  sub,
  color,
}: {
  icon: React.ElementType;
  label: string;
  value: string | number;
  sub?: string;
  color: string;
}) {
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="flex items-center gap-3">
        <div
          className={`flex size-9 items-center justify-center rounded-lg bg-muted`}
          style={{ color }}
        >
          <Icon className="size-4" />
        </div>
        <div>
          <p className="text-xs text-muted-foreground">{label}</p>
          <p className="text-lg font-bold text-foreground">{value}</p>
          {sub && <p className="text-xs text-muted-foreground">{sub}</p>}
        </div>
      </div>
    </div>
  );
}

function DifficultyTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ value: number; payload: DifficultyDistribution }>;
}) {
  const { t } = useTranslation("dashboard");
  if (!active || !payload?.length) return null;
  const item = payload[0].payload;
  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2 shadow-lg">
      <p className="text-sm font-semibold text-foreground">{item.difficulty}</p>
      <p className="text-xs text-muted-foreground">{t("charts.solved", { count: item.count })}</p>
    </div>
  );
}

export function StatsPanel({ stats }: StatsPanelProps) {
  const { t } = useTranslation("dashboard");
  const hasDistribution = stats.difficulty_distribution.length > 0;
  const hasChallenges = stats.challenge_total > 0;

  return (
    <div className="space-y-4">
      {/* Summary stat cards */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          icon={Target}
          label={t("charts.totalSolved")}
          value={stats.total_solved}
          color="#6366f1"
        />
        <StatCard
          icon={Swords}
          label={t("charts.challengeWinRate")}
          value={hasChallenges ? `${stats.challenge_win_rate.toFixed(1)}%` : "-"}
          sub={hasChallenges ? t("charts.winRateSub", { wins: stats.challenge_wins, total: stats.challenge_total }) : undefined}
          color="#ef4444"
        />
        <StatCard
          icon={TrendingUp}
          label={t("charts.tokensEarned")}
          value={stats.total_tokens_earned}
          color="#22c55e"
        />
        <StatCard
          icon={Coins}
          label={t("charts.tokensSpent")}
          value={stats.total_tokens_spent}
          color="#f59e0b"
        />
      </div>

      {/* Difficulty distribution chart */}
      <div className="rounded-xl border border-border bg-card p-5">
        <h3 className="mb-4 text-sm font-semibold text-foreground">{t("charts.difficultyDistribution")}</h3>
        {hasDistribution ? (
          <div className="flex flex-col items-center gap-4 sm:flex-row">
            <div className="w-full sm:w-1/2">
              <ResponsiveContainer width="100%" height={180}>
                <PieChart>
                  <Pie
                    data={stats.difficulty_distribution}
                    dataKey="count"
                    nameKey="difficulty"
                    cx="50%"
                    cy="50%"
                    innerRadius={40}
                    outerRadius={70}
                    paddingAngle={2}
                    stroke="none"
                  >
                    {stats.difficulty_distribution.map((entry, index) => (
                      <Cell key={index} fill={entry.color} fillOpacity={0.85} />
                    ))}
                  </Pie>
                  <Tooltip content={<DifficultyTooltip />} />
                </PieChart>
              </ResponsiveContainer>
            </div>
            <div className="w-full space-y-2 sm:w-1/2">
              {stats.difficulty_distribution.map((d) => (
                <div key={d.difficulty} className="flex items-center justify-between text-sm">
                  <div className="flex items-center gap-2">
                    <span
                      className="inline-block size-3 rounded-sm"
                      style={{ backgroundColor: d.color }}
                    />
                    <span className="text-muted-foreground">{d.difficulty}</span>
                  </div>
                  <span className="font-medium text-foreground">{d.count}</span>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <div className="flex h-[120px] items-center justify-center text-sm text-muted-foreground">
            {t("charts.noStats")}
          </div>
        )}
      </div>
    </div>
  );
}
