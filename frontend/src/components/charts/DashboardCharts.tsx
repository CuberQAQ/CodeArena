import { useEffect, useState, useCallback } from "react";
import { RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import api from "@/services/api";
import { getMElo } from "@/services/trainingApi";
import { useAuthStore } from "@/stores/auth";
import type {
  ApiResponse,
  TransactionItem,
  EloHistoryPoint,
  RadarDataPoint,
  PPContributionItem,
  DashboardStats,
  DifficultyDistribution,
} from "@/types";
import { getRatingColor, getDifficultyLabelKey } from "@/utils";
import { EloChart } from "./EloChart";
import { RadarChart } from "./RadarChart";
import { PPChart } from "./PPChart";
import { StatsPanel } from "./StatsPanel";

// ---------------------------------------------------------------------------
// Data transformation helpers
// ---------------------------------------------------------------------------

/** Map CF tag names to training locale topic keys. */
const CF_TAG_TO_SLUG: Record<string, string> = {
  dp: "dp",
  greedy: "greedy",
  math: "math",
  graphs: "graphs",
  strings: "strings",
  "data structures": "data_structures",
  "binary search": "binary_search",
  sortings: "sorting",
  "constructive algorithms": "constructive",
  "number theory": "number_theory",
  trees: "trees",
  geometry: "geometry",
};

function buildRadarDataFromMElo(
  melos: { tag: string; elo: number; shield_active: boolean }[],
  globalElo: number,
  t: (key: string, fallback?: string) => string,
): RadarDataPoint[] {
  if (melos.length === 0) return [];

  const raw = melos.map((m) => {
    const slug = CF_TAG_TO_SLUG[m.tag];
    const label = slug ? t(`training:topic.${slug}`, m.tag) : m.tag;
    return {
      topic: label.length > 8 ? label.slice(0, 7) + "." : label,
      value: m.shield_active ? globalElo : m.elo,
      fullMark: 0, // placeholder, computed below
    };
  });

  const maxVal = Math.max(...raw.map((r) => r.value), 0.1);
  const fullMark = Math.max(maxVal * 1.3, maxVal + 0.1);
  return raw.map((r) => ({ ...r, fullMark }));
}

function buildStatsFromData(
  transactions: TransactionItem[],
  userSolved: number,
  radarData: RadarDataPoint[],
  ppContributions: PPContributionItem[],
  t: (key: string) => string,
): DashboardStats {
  let totalEarned = 0;
  let totalSpent = 0;

  for (const tx of transactions) {
    if (tx.amount > 0) totalEarned += tx.amount;
    else totalSpent += Math.abs(tx.amount);
  }

  const _DIST_BUCKETS = [
    { max: 1199, rating: 800 },
    { max: 1399, rating: 1300 },
    { max: 1599, rating: 1500 },
    { max: 1899, rating: 1800 },
    { max: 2099, rating: 2000 },
    { max: Infinity, rating: 2600 },
  ];

  let difficultyDistribution: DifficultyDistribution[] = [];

  // Build distribution from PP contributions (actual solved problem ratings)
  if (ppContributions.length > 0) {
    const buckets = _DIST_BUCKETS.map(() => 0);
    for (const pp of ppContributions) {
      if (pp.rating == null) continue;
      for (let i = 0; i < _DIST_BUCKETS.length; i++) {
        if (pp.rating <= _DIST_BUCKETS[i].max) {
          buckets[i]++;
          break;
        }
      }
    }
    difficultyDistribution = _DIST_BUCKETS
      .map((b, i) => ({
        difficulty: t(getDifficultyLabelKey(b.rating)),
        count: buckets[i],
        color: getRatingColor(b.rating),
      }))
      .filter((d) => d.count > 0);
  } else if (radarData.length > 0 && userSolved > 0) {
    // Fallback: estimate from M-Elo weights
    const _WEIGHTS = [0.35, 0.25, 0.20, 0.12, 0.06, 0.02];
    difficultyDistribution = _DIST_BUCKETS.map((b, i) => ({
      difficulty: t(getDifficultyLabelKey(b.rating)),
      count: Math.round(userSolved * _WEIGHTS[i]),
      color: getRatingColor(b.rating),
    })).filter((d) => d.count > 0);
  }

  return {
    total_solved: userSolved,
    difficulty_distribution: difficultyDistribution,
    challenge_win_rate: 0,
    challenge_total: 0,
    challenge_wins: 0,
    total_tokens_earned: totalEarned,
    total_tokens_spent: totalSpent,
  };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function DashboardCharts({ transactions }: { transactions: TransactionItem[] }) {
  const { user } = useAuthStore();
  const { t } = useTranslation(["dashboard", "training"]);
  const [loading, setLoading] = useState(true);
  const [eloData, setEloData] = useState<EloHistoryPoint[]>([]);
  const [radarData, setRadarData] = useState<RadarDataPoint[]>([]);
  const [ppData, setPpData] = useState<PPContributionItem[]>([]);
  const [stats, setStats] = useState<DashboardStats>({
    total_solved: 0,
    difficulty_distribution: [],
    challenge_win_rate: 0,
    challenge_total: 0,
    challenge_wins: 0,
    total_tokens_earned: 0,
    total_tokens_spent: 0,
  });

  const fetchAllData = useCallback(async () => {
    if (!user) return;
    setLoading(true);

    try {
      // Fetch M-Elo data (for radar chart)
      const meloResult = await getMElo().catch(() => null);

      // --- Radar data (M-Elo) ---
      let radar: RadarDataPoint[] = [];
      let totalSolved = 0;
      if (meloResult && meloResult.melos.length > 0) {
        radar = buildRadarDataFromMElo(meloResult.melos, meloResult.global_elo, t);
        totalSolved = meloResult.melos.reduce((sum, m) => sum + m.total_submissions, 0);
      }
      setRadarData(radar);

      // Elo history
      const eloResult = await api
        .get<ApiResponse<EloHistoryPoint[]>>("/auth/elo-history")
        .then((r) => r.data.data)
        .catch(() => []);
      setEloData(eloResult);

      // PP contributions
      const ppResult = await api
        .get<ApiResponse<PPContributionItem[]>>("/auth/pp-contributions?limit=100")
        .then((r) => r.data.data ?? [])
        .catch(() => []);
      setPpData(ppResult);

      // Use PP count as a more accurate total_solved if M-Elo submissions are 0
      if (totalSolved === 0 && ppResult.length > 0) {
        totalSolved = ppResult.length;
      }

      setStats(buildStatsFromData(transactions, totalSolved, radar, ppResult, t));
    } catch {
      // Silently fail - charts show empty state
    } finally {
      setLoading(false);
    }
  }, [user, t, transactions]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- data fetch updates state via callbacks
    fetchAllData();
  }, [fetchAllData]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-foreground">{t("analytics")}</h2>
        <Button
          variant="ghost"
          size="xs"
          disabled={loading}
          onClick={fetchAllData}
        >
          <RefreshCw className={`size-3.5 ${loading ? "animate-spin" : ""}`} />
        </Button>
      </div>

      {/* Top row: Elo trend + Skill radar */}
      <div className="grid gap-4 lg:grid-cols-2">
        <EloChart data={eloData} />
        <RadarChart data={radarData} />
      </div>

      {/* PP contributions */}
      <PPChart data={ppData} />

      {/* Stats panel */}
      <StatsPanel stats={stats} />
    </div>
  );
}
