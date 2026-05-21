import { useEffect, useRef, useState } from "react";
import { BarChart3, TrendingUp, Medal } from "lucide-react";
import { useTranslation } from "react-i18next";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { getRatingColor, getDifficultyLabelKey, ratingToMedal } from "@/utils";
import { MedalBadge } from "@/components/medal";
import { Avatar } from "@/components/Avatar";
import api from "@/services/api";
import type { ApiResponse, UserInfo, UserSettingsData } from "@/types";

type SortKey = "elo" | "pp";

export default function LeaderboardPage() {
  const { t } = useTranslation("leaderboard");
  const [users, setUsers] = useState<UserInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [sortBy, setSortBy] = useState<SortKey>("elo");
  const [displayMode, setDisplayMode] = useState<"medal" | "cf_tier">("medal");
  const hasFetchedRef = useRef(false);

  useEffect(() => {
    if (hasFetchedRef.current) return;
    hasFetchedRef.current = true;
    api
      .get<ApiResponse<UserInfo[]>>("/auth/leaderboard")
      .then((res) => setUsers(res.data.data ?? []))
      .catch(() => {
        setUsers([]);
      })
      .finally(() => setLoading(false));
    api
      .get<ApiResponse<UserSettingsData>>("/auth/settings")
      .then((res) => setDisplayMode(res.data.data.display_mode))
      .catch(() => {});
  }, []);

  const sorted = [...users].sort((a, b) =>
    sortBy === "elo" ? b.elo - a.elo : b.pp - a.pp,
  );

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-foreground">{t("leaderboard")}</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {t("leaderboardDesc")}
        </p>
      </div>

      {/* Sort tabs */}
      <div className="flex gap-2">
        <button
          onClick={() => setSortBy("elo")}
          className={`flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
            sortBy === "elo"
              ? "bg-primary text-primary-foreground"
              : "bg-muted text-muted-foreground hover:text-foreground"
          }`}
        >
          <TrendingUp className="size-4" />
          {t("byElo")}
        </button>
        <button
          onClick={() => setSortBy("pp")}
          className={`flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
            sortBy === "pp"
              ? "bg-primary text-primary-foreground"
              : "bg-muted text-muted-foreground hover:text-foreground"
          }`}
        >
          <Medal className="size-4" />
          {t("byPP")}
        </button>
      </div>

      {loading ? (
        <LoadingSpinner text={t("loadingLeaderboard")} className="py-20" />
      ) : sorted.length === 0 ? (
        <div className="rounded-xl border border-border bg-card px-4 py-12 text-center">
          <BarChart3 className="mx-auto size-10 text-muted-foreground" />
          <p className="mt-3 text-sm text-muted-foreground">
            {t("noData")}
          </p>
        </div>
      ) : (
        <div className="rounded-xl border border-border bg-card">
          {/* Header row */}
          <div className="grid grid-cols-[3rem_1fr_7rem_5rem_5rem] items-center border-b border-border px-5 py-2.5 text-xs font-medium text-muted-foreground">
            <span>#</span>
            <span>{t("player")}</span>
            <span className="text-right">{t("elo")}</span>
            <span className="text-right">{t("pp")}</span>
            <span className="text-right">{t("tokens")}</span>
          </div>
          <div className="divide-y divide-border">
            {sorted.map((user, index) => (
              <div
                key={user.id}
                className="grid grid-cols-[3rem_1fr_7rem_5rem_5rem] items-center px-5 py-3 transition-colors hover:bg-muted/50"
              >
                <span className="text-sm font-medium text-muted-foreground">
                  {index + 1}
                </span>
                <div className="flex min-w-0 items-center gap-2">
                  <Avatar userId={user.id} src={user.avatar_path} size={28} />
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-foreground">{user.username}</p>
                    {user.cf_handle && (
                      <p className="truncate text-xs text-muted-foreground">
                        {t("cfHandle", { handle: user.cf_handle })}
                      </p>
                    )}
                  </div>
                </div>
                <span
                  className="text-right text-sm font-bold"
                  style={{ color: getRatingColor(user.elo) }}
                >
                  {displayMode === "medal" ? (
                    (() => {
                      const medal = ratingToMedal(user.elo);
                      return (
                        <span className="inline-flex items-center gap-1">
                          {user.elo}
                          <MedalBadge
                            level={medal.level}
                            type={medal.type}
                            size="sm"
                          />
                        </span>
                      );
                    })()
                  ) : (
                    <>
                      {user.elo} <span className="text-xs font-medium">/ {t(getDifficultyLabelKey(user.elo))}</span>
                    </>
                  )}
                </span>
                <span className="text-right text-sm font-semibold text-yellow-400">
                  {user.pp}
                </span>
                <span className="text-right text-sm text-muted-foreground">{user.tokens}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
