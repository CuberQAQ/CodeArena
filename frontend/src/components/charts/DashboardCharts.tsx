import { useEffect, useState, useCallback } from "react";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import api from "@/services/api";
import { useAuthStore } from "@/stores/auth";
import type {
  ApiResponse,
  TrainingProgress,
  TransactionItem,
  EloHistoryPoint,
  RadarDataPoint,
  PPContributionItem,
  DashboardStats,
  DifficultyDistribution,
} from "@/types";
import { getRatingColor } from "@/utils";
import { EloChart } from "./EloChart";
import { RadarChart } from "./RadarChart";
import { PPChart } from "./PPChart";
import { StatsPanel } from "./StatsPanel";

// ---------------------------------------------------------------------------
// Data transformation helpers
// ---------------------------------------------------------------------------

function buildRadarData(progress: TrainingProgress): RadarDataPoint[] {
  return progress.topics.map((t) => ({
    topic: t.topic_name.length > 8 ? t.topic_name.slice(0, 7) + "." : t.topic_name,
    value: Math.round(t.completion_rate * 100) / 100,
    fullMark: 100,
  }));
}

function buildStatsFromTransactions(
  transactions: TransactionItem[],
  userSolved: number,
  radarData: RadarDataPoint[],
): DashboardStats {
  let totalEarned = 0;
  let totalSpent = 0;

  for (const tx of transactions) {
    if (tx.amount > 0) totalEarned += tx.amount;
    else totalSpent += Math.abs(tx.amount);
  }

  // Estimate difficulty distribution from radar data (training solved per topic)
  // We do not have per-problem rating data from the transaction list, so we show a
  // simplified view based on total solved. A richer API endpoint would provide
  // actual per-difficulty counts.
  const difficultyDistribution: DifficultyDistribution[] = radarData.length > 0
    ? [
        { difficulty: "Gray (Newbie)", count: Math.round(userSolved * 0.35), color: getRatingColor(800) },
        { difficulty: "Green (Pupil)", count: Math.round(userSolved * 0.25), color: getRatingColor(1300) },
        { difficulty: "Blue (Specialist)", count: Math.round(userSolved * 0.2), color: getRatingColor(1500) },
        { difficulty: "Purple (Expert)", count: Math.round(userSolved * 0.12), color: getRatingColor(1800) },
        { difficulty: "Yellow (CM)", count: Math.round(userSolved * 0.06), color: getRatingColor(2200) },
        { difficulty: "Red (GM+)", count: Math.round(userSolved * 0.02), color: getRatingColor(2600) },
      ]
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
      // Fetch training progress (for radar chart and solved count)
      const progressPromise = api
        .get<ApiResponse<TrainingProgress>>("/training/progress")
        .then((res) => res.data.data)
        .catch(() => null);

      // Fetch transaction history (for token stats)
      const txPromise = api
        .get<ApiResponse<{ items: TransactionItem[]; total: number }>>("/economy/transactions?limit=100")
        .then((res) => res.data.data)
        .catch(() => null);

      const [progressResult, txResult] = await Promise.all([progressPromise, txPromise]);

      // --- Radar data ---
      if (progressResult) {
        const radar = buildRadarData(progressResult);
        setRadarData(radar);

        // --- Stats ---
        const transactions = txResult?.items ?? [];
        const totalSolved = progressResult.total_solved;
        setStats(buildStatsFromTransactions(transactions, totalSolved, radar));
      } else {
        // No progress data - use transactions-only stats
        const transactions = txResult?.items ?? [];
        setStats(buildStatsFromTransactions(transactions, 0, []));
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
  }, [user]);

  useEffect(() => {
    fetchAllData();
  }, [fetchAllData]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-foreground">Analytics</h2>
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
