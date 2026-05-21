import { useCallback, useEffect, useRef, useState } from "react";
import { Globe, ShieldCheck, BarChart3, ChevronLeft, ChevronRight, Search, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import api from "@/services/api";
import type { ApiResponse, GlobalRankingItem, ArenaRankingItem, RankingPageData } from "@/types";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

type TabKey = "global" | "arena";
type ArenaSortKey = "pp" | "elo";
const PAGE_SIZE = 50;

// ---------------------------------------------------------------------------
// Skeleton row component
// ---------------------------------------------------------------------------

function SkeletonRows({ count = 8, cols = 4 }: { count?: number; cols?: number }) {
  return (
    <div className="divide-y divide-border">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="flex items-center gap-4 px-5 py-3">
          {Array.from({ length: cols }).map((_, j) => (
            <div
              key={j}
              className="h-4 animate-pulse rounded bg-muted"
              style={{ width: j === 1 ? "40%" : j === 0 ? "3rem" : "5rem" }}
            />
          ))}
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function GlobalRankingPage() {
  const { t } = useTranslation("ranking");

  // Tab & filter state
  const [activeTab, setActiveTab] = useState<TabKey>("global");
  const [arenaSort, setArenaSort] = useState<ArenaSortKey>("pp");
  const [countryFilter, setCountryFilter] = useState("");
  const [appliedCountry, setAppliedCountry] = useState<string | null>(null);

  // Pagination state
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [total, setTotal] = useState(0);

  // Data state
  const [globalItems, setGlobalItems] = useState<GlobalRankingItem[]>([]);
  const [arenaItems, setArenaItems] = useState<ArenaRankingItem[]>([]);
  const [loading, setLoading] = useState(true);

  // Debounce timer ref for country input
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ---- Fetch global ranking ----
  const fetchGlobal = useCallback(async (p: number, country: string | null) => {
    setLoading(true);
    try {
      const params: Record<string, unknown> = { page: p, page_size: PAGE_SIZE };
      if (country) params.country = country;
      const res = await api.get<ApiResponse<RankingPageData<GlobalRankingItem>>>("/ranking/global", { params });
      const data = res.data.data;
      setGlobalItems(data.items);
      setTotal(data.total);
      setTotalPages(Math.max(1, Math.ceil(data.total / PAGE_SIZE)));
    } catch {
      setGlobalItems([]);
      setTotal(0);
      setTotalPages(1);
    } finally {
      setLoading(false);
    }
  }, []);

  // ---- Fetch arena ranking ----
  const fetchArena = useCallback(async (p: number, country: string | null, sortBy: ArenaSortKey) => {
    setLoading(true);
    try {
      const params: Record<string, unknown> = { page: p, page_size: PAGE_SIZE, sort_by: sortBy };
      if (country) params.country = country;
      const res = await api.get<ApiResponse<RankingPageData<ArenaRankingItem>>>("/ranking/arena", { params });
      const data = res.data.data;
      setArenaItems(data.items);
      setTotal(data.total);
      setTotalPages(Math.max(1, Math.ceil(data.total / PAGE_SIZE)));
    } catch {
      setArenaItems([]);
      setTotal(0);
      setTotalPages(1);
    } finally {
      setLoading(false);
    }
  }, []);

  // ---- Re-fetch when page/country/sort changes ----
  useEffect(() => {
    if (activeTab === "global") {
      fetchGlobal(page, appliedCountry);
    } else {
      fetchArena(page, appliedCountry, arenaSort);
    }
  }, [activeTab, page, appliedCountry, arenaSort, fetchGlobal, fetchArena]);

  // ---- Tab switch handler ----
  const handleTabChange = (tab: TabKey) => {
    setActiveTab(tab);
    setPage(1);
  };

  // ---- Arena sort handler ----
  const handleArenaSort = (sortBy: ArenaSortKey) => {
    setArenaSort(sortBy);
    setPage(1);
  };

  // ---- Country filter with debounce ----
  const handleCountryInput = (value: string) => {
    setCountryFilter(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      const trimmed = value.trim().toUpperCase();
      setAppliedCountry(trimmed.length === 2 ? trimmed : null);
      setPage(1);
    }, 400);
  };

  const handleClearCountry = () => {
    setCountryFilter("");
    setAppliedCountry(null);
    setPage(1);
  };

  // ---- Pagination helpers ----
  const handlePrevPage = () => setPage((p) => Math.max(1, p - 1));
  const handleNextPage = () => setPage((p) => Math.min(totalPages, p + 1));

  // ---- Current data ----
  const items = activeTab === "global" ? globalItems : arenaItems;

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-foreground">{t("title")}</h1>
        <p className="mt-1 text-sm text-muted-foreground">{t("description")}</p>
      </div>

      {/* Tab + Filter bar */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        {/* Tabs */}
        <div className="flex gap-2">
          <button
            onClick={() => handleTabChange("global")}
            className={`flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
              activeTab === "global"
                ? "bg-primary text-primary-foreground"
                : "bg-muted text-muted-foreground hover:text-foreground"
            }`}
          >
            <Globe className="size-4" />
            {t("tabGlobal")}
          </button>
          <button
            onClick={() => handleTabChange("arena")}
            className={`flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
              activeTab === "arena"
                ? "bg-primary text-primary-foreground"
                : "bg-muted text-muted-foreground hover:text-foreground"
            }`}
          >
            <BarChart3 className="size-4" />
            {t("tabArena")}
          </button>
        </div>

        {/* Country filter */}
        <div className="flex items-center gap-2">
          {activeTab === "arena" && (
            <div className="flex gap-1 mr-2">
              <button
                onClick={() => handleArenaSort("pp")}
                className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                  arenaSort === "pp"
                    ? "bg-secondary text-secondary-foreground"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {t("sortByPP")}
              </button>
              <button
                onClick={() => handleArenaSort("elo")}
                className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                  arenaSort === "elo"
                    ? "bg-secondary text-secondary-foreground"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {t("sortByElo")}
              </button>
            </div>
          )}
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
            <input
              type="text"
              value={countryFilter}
              onChange={(e) => handleCountryInput(e.target.value)}
              placeholder={t("countryPlaceholder")}
              maxLength={2}
              className="h-9 w-28 rounded-lg border border-border bg-background pl-8 pr-7 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
            />
            {countryFilter && (
              <button
                onClick={handleClearCountry}
                className="absolute right-1.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              >
                <X className="size-3.5" />
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Tab description */}
      <p className="text-xs text-muted-foreground">
        {activeTab === "global" ? t("globalDesc") : t("arenaDesc")}
      </p>

      {/* Ranking table */}
      {loading ? (
        <div className="rounded-xl border border-border bg-card">
          <div className={`items-center border-b border-border px-5 py-2.5 text-xs font-medium text-muted-foreground ${
              activeTab === "arena"
                ? "grid grid-cols-[3.5rem_1fr_5rem_5rem_5rem_3rem]"
                : "grid grid-cols-[3.5rem_1fr_5rem_5rem_3rem]"
            }`}>
            <span>{t("rank")}</span>
            <span>{t("name")}</span>
            <span className="text-right">{t("pp")}</span>
            {activeTab === "arena" && <span className="text-right">{t("elo")}</span>}
            <span className="text-right">{t("country")}</span>
          </div>
          <SkeletonRows count={8} cols={activeTab === "arena" ? 5 : 4} />
        </div>
      ) : items.length === 0 ? (
        <div className="rounded-xl border border-border bg-card px-4 py-12 text-center">
          <BarChart3 className="mx-auto size-10 text-muted-foreground" />
          <p className="mt-3 text-sm text-muted-foreground">{t("noData")}</p>
        </div>
      ) : (
        <div className="rounded-xl border border-border bg-card">
          {/* Header row */}
          <div
            className={`items-center border-b border-border px-5 py-2.5 text-xs font-medium text-muted-foreground ${
              activeTab === "arena"
                ? "grid grid-cols-[3.5rem_1fr_5rem_5rem_5rem_3rem]"
                : "grid grid-cols-[3.5rem_1fr_5rem_5rem_3rem]"
            }`}
          >
            <span>{t("rank")}</span>
            <span>{t("name")}</span>
            <span className="text-right">{t("pp")}</span>
            {activeTab === "arena" && <span className="text-right">{t("elo")}</span>}
            <span className="text-right">{t("country")}</span>
            <span /> {/* verified icon column */}
          </div>

          {/* Data rows */}
          <div className="divide-y divide-border">
            {(activeTab === "global" ? globalItems : arenaItems).map((item, idx) => {
              const isGlobal = activeTab === "global";
              const globalItem = item as GlobalRankingItem;
              const arenaItem = item as ArenaRankingItem;
              const computedRank = (page - 1) * PAGE_SIZE + idx + 1;

              return (
                <div
                  key={`${computedRank}-${item.name}`}
                  className={`items-center px-5 py-3 transition-colors hover:bg-muted/50 ${
                    activeTab === "arena"
                      ? "grid grid-cols-[3.5rem_1fr_5rem_5rem_5rem_3rem]"
                      : "grid grid-cols-[3.5rem_1fr_5rem_5rem_3rem]"
                  }`}
                >
                  {/* Rank */}
                  <span className="text-sm font-medium text-muted-foreground">
                    {computedRank}
                  </span>

                  {/* Name */}
                  <div className="flex min-w-0 items-center gap-2">
                    <p className="truncate text-sm font-medium text-foreground">{item.name}</p>
                    {isGlobal && !item.verified && globalItem.cf_rating != null && (
                      <span className="shrink-0 text-xs text-muted-foreground">
                        ({globalItem.cf_rating})
                      </span>
                    )}
                  </div>

                  {/* PP */}
                  <span className="text-right text-sm font-semibold text-yellow-400">
                    {item.pp}
                  </span>

                  {/* Elo (arena only) */}
                  {activeTab === "arena" && (
                    <span className="text-right text-sm font-semibold text-foreground">
                      {arenaItem.elo}
                    </span>
                  )}

                  {/* Country */}
                  <span className="text-right text-sm text-muted-foreground uppercase">
                    {item.country ?? "-"}
                  </span>

                  {/* Verified badge + top % */}
                  <span className="flex items-center justify-end gap-1.5">
                    {item.verified ? (
                      <>
                        {total > 0 && (
                          <span className="text-[10px] font-medium text-emerald-400">
                            {t("topPercent", { percent: ((computedRank / total) * 100).toFixed(1) })}
                          </span>
                        )}
                        <span title={t("verifiedTooltip")}>
                          <ShieldCheck className="size-4 text-primary" />
                        </span>
                      </>
                    ) : (
                      <span title={t("cfUserTooltip")}>
                        <Globe className="size-4 text-muted-foreground/40" />
                      </span>
                    )}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Pagination */}
      {!loading && total > 0 && (
        <div className="flex items-center justify-between">
          <span className="text-sm text-muted-foreground">
            {t("totalUsers", { count: total })}
          </span>
          <div className="flex items-center gap-3">
            <Button
              variant="outline"
              size="sm"
              disabled={page <= 1}
              onClick={handlePrevPage}
            >
              <ChevronLeft className="mr-1 size-4" />
              {t("prevPage")}
            </Button>
            <span className="text-sm text-muted-foreground">
              {t("page", { current: page, total: totalPages })}
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={page >= totalPages}
              onClick={handleNextPage}
            >
              {t("nextPage")}
              <ChevronRight className="ml-1 size-4" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
