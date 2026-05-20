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

function buildRadarDataFromMElo(
  melos: { tag: string; elo: number; shield_active: boolean }[],
  globalElo: number,
): RadarDataPoint[] {
  if (melos.length === 0) return [];

  const raw = melos.map((m) => ({
    topic: m.tag.length > 8 ? m.tag.slice(0, 7) + "." : m.tag,
    value: m.shield_active ? globalElo : m.elo,
    fullMark: 0, // placeholder, computed below
  }));

  const maxVal = Math.max(...raw.map((r) => r.value), 0.1);
  const fullMark = Math.max(maxVal * 1.3, maxVal + 0.1);
  return raw.map((r) => ({ ...r, fullMark }));
}

function buildStatsFromTransactions(
  transactions: TransactionItem[],
  userSolved: number,
  radarData: RadarDataPoint[],
  t: (key: string) => string,
): DashboardStats {
  let totalEarned = 0;
  let totalSpent = 0;

  for (const tx of transactions) {
    if (tx.amount > 0) totalEarned += tx.amount;
    else totalSpent += Math.abs(tx.amount);
  }

  const _DIST_WEIGHTS = [
    { rating: 800, weight: 0.35 },
    { rating: 1300, weight: 0.25 },
    { rating: 1500, weight: 0.20 },
    { rating: 1800, weight: 0.12 },
    { rating: 2000, weight: 0.06 },
    { rating: 2600, weight: 0.02 },
  ];

  const difficultyDistribution: DifficultyDistribution[] = radarData.length > 0
    ? _DIST_WEIGHTS.map(({ rating, weight }) => ({
        difficulty: t(getDifficultyLabelKey(rating)),
        count: Math.round(userSolved * weight),
        color: getRatingColor(rating),
      }))
    : [];

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

export function DashboardCharts() {
  const { user } = useAuthStore();
  const { t } = useTranslation("dashboard");
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
      const meloPromise = getMElo().catch(() => null);

      // Fetch transaction history (for token stats)
      const txPromise = api
        .get<ApiResponse<{ items: TransactionItem[]; total: number }>>("/economy/transactions?limit=100")
        .then((res) => res.data.data)
        .catch(() => null);

      const [meloResult, txResult] = await Promise.all([meloPromise, txPromise]);

      // --- Radar data (M-Elo) ---
      if (meloResult && meloResult.melos.length > 0) {
        const radar = buildRadarDataFromMElo(meloResult.melos, meloResult.global_elo);
        setRadarData(radar);

        // --- Stats ---
        const transactions = txResult?.items ?? [];
        // Estimate total solved from M-Elo submissions
        const totalSolved = meloResult.melos.reduce((sum, m) => sum + m.total_submissions, 0);
        setStats(buildStatsFromTransactions(transactions, totalSolved, radar, t));
      } else {
        // No M-Elo data - use transactions-only stats
        const transactions = txResult?.items ?? [];
        setRadarData([]);
        setStats(buildStatsFromTransactions(transactions, 0, [], t));
      }

      // Elo history
      const eloResult = await api
        .get<ApiResponse<EloHistoryPoint[]>>("/auth/elo-history")
        .then((r) => r.data.data)
        .catch(() => []);
      setEloData(eloResult);

      // PP contributions
      const ppResult = await api
        .get<ApiResponse<PPContributionItem[]>>("/auth/pp-contributions?limit=20")
        .then((r) => r.data.data)
        .catch(() => []);
      setPpData(ppResult);
    } catch {
      // Silently fail - charts show empty state
    } finally {
      setLoading(false);
    }
  }, [user, t]);

  useEffect(() => {
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
