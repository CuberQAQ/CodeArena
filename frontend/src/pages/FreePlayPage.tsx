/** Free Play main page.
 *
 * Two modes (switched by tab):
 *   1. Manual Filter  - rating range slider + tag chips -> search
 *   2. Adaptive Rec.   - one-click recommendation based on M-Elo
 *
 * After a problem is selected/found the user clicks "Start Problem" and is
 * redirected to /free-play/session/:id.
 */

import { useCallback, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import {
  Search,
  Sparkles,
  X,
  Plus,
  Loader2,
  Compass,
  Filter,
  Star,
  ExternalLink,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { getRatingColor } from "@/utils";
import * as freePlayApi from "@/services/freePlayApi";
import type { FreePlayProblemInfo } from "@/types";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PRESET_TAGS = [
  "dp",
  "greedy",
  "math",
  "graphs",
  "dfs and similar",
  "binary search",
  "constructive algorithms",
  "data structures",
  "brute force",
  "two pointers",
  "sortings",
  "strings",
];

const EXTRA_TAGS = [
  "trees",
  "dsu",
  "combinatorics",
  "geometry",
  "number theory",
  "divide and conquer",
  "interactive",
  "bitmasks",
  "hashing",
  "games",
  "matrices",
  "scheduling",
  "ternary search",
  "meet-in-the-middle",
  "expression parsing",
  "graph matchings",
  "probabilities",
  "fft",
  "flows",
  "chinese remainder theorem",
  "2-sat",
];

const ALL_TAGS = [...PRESET_TAGS, ...EXTRA_TAGS];

const RATING_MIN = 800;
const RATING_MAX = 3500;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Map a 0..100 slider position to a rating value in [RATING_MIN, RATING_MAX]. */
function sliderToRating(pos: number): number {
  return Math.round(RATING_MIN + (pos / 100) * (RATING_MAX - RATING_MIN));
}

/** Map a rating value to a 0..100 slider position. */
function ratingToSlider(rating: number): number {
  return ((rating - RATING_MIN) / (RATING_MAX - RATING_MIN)) * 100;
}

// ---------------------------------------------------------------------------
// TagChip
// ---------------------------------------------------------------------------

function TagChip({
  tag,
  selected,
  onToggle,
}: {
  tag: string;
  selected: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
        selected
          ? "bg-primary text-primary-foreground"
          : "bg-muted text-muted-foreground hover:bg-muted/80"
      }`}
    >
      {tag}
    </button>
  );
}

// ---------------------------------------------------------------------------
// MoreTagsDialog
// ---------------------------------------------------------------------------

function MoreTagsDialog({
  open,
  onClose,
  selectedTags,
  onToggleTag,
}: {
  open: boolean;
  onClose: () => void;
  selectedTags: Set<string>;
  onToggleTag: (tag: string) => void;
}) {
  const { t } = useTranslation("free_play");
  const [search, setSearch] = useState("");

  const filtered = useMemo(
    () =>
      search
        ? ALL_TAGS.filter((tag) => tag.toLowerCase().includes(search.toLowerCase()))
        : ALL_TAGS,
    [search],
  );

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="mx-4 w-full max-w-md rounded-xl border border-border bg-card p-5 shadow-xl">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-foreground">{t("moreTagsTitle")}</h3>
          <button onClick={onClose} className="rounded-md p-1 text-muted-foreground hover:text-foreground">
            <X className="size-4" />
          </button>
        </div>

        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={t("searchTagsPlaceholder")}
          className="mt-3 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/50"
        />

        <div className="mt-3 flex max-h-60 flex-wrap gap-1.5 overflow-y-auto">
          {filtered.map((tag) => (
            <TagChip
              key={tag}
              tag={tag}
              selected={selectedTags.has(tag)}
              onToggle={() => onToggleTag(tag)}
            />
          ))}
          {filtered.length === 0 && (
            <p className="text-xs text-muted-foreground">-</p>
          )}
        </div>

        <div className="mt-4 flex justify-end">
          <Button size="sm" onClick={onClose}>
            OK
          </Button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// ProblemCard -- shown after search/recommend returns a problem
// ---------------------------------------------------------------------------

function ProblemCard({
  problem,
  onStart,
  starting,
}: {
  problem: FreePlayProblemInfo;
  onStart: () => void;
  starting: boolean;
}) {
  const { t } = useTranslation(["free_play", "common"]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="rounded-xl border-2 border-primary/30 bg-card p-5"
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-lg font-bold text-foreground">{problem.name}</h3>
          <p className="mt-1 text-sm text-muted-foreground">
            {problem.contest_id}
            {problem.index}
          </p>
        </div>
        {problem.rating != null && (
          <span
            className="shrink-0 rounded-lg px-3 py-1 text-sm font-bold"
            style={{
              color: getRatingColor(problem.rating),
              backgroundColor: `${getRatingColor(problem.rating)}20`,
            }}
          >
            {problem.rating}
          </span>
        )}
      </div>

      {problem.tags.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {problem.tags.map((tag) => (
            <span
              key={tag}
              className="rounded-md bg-muted px-2 py-0.5 text-xs text-muted-foreground"
            >
              {tag}
            </span>
          ))}
        </div>
      )}

      <div className="mt-4 flex items-center gap-3">
        <Button onClick={onStart} disabled={starting}>
          {starting ? (
            <>
              <Loader2 className="mr-2 size-4 animate-spin" />
              {t("free_play:starting")}
            </>
          ) : (
            <>
              <Star className="mr-2 size-4" />
              {t("free_play:startProblem")}
            </>
          )}
        </Button>
        <a
          href={problem.url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-xs text-primary hover:text-primary/80"
        >
          <ExternalLink className="size-3" />
          {t("common:openOnCodeforces", { defaultValue: "Open on Codeforces" })}
        </a>
      </div>
    </motion.div>
  );
}

// ---------------------------------------------------------------------------
// Main page component
// ---------------------------------------------------------------------------

export default function FreePlayPage() {
  const navigate = useNavigate();
  const { t } = useTranslation("free_play");

  // Tab state
  const [tab, setTab] = useState<"manual" | "recommend">("manual");

  // Manual filter state
  const [minRating, setMinRating] = useState(1200);
  const [maxRating, setMaxRating] = useState(2000);
  const [selectedTags, setSelectedTags] = useState<Set<string>>(new Set());
  const [moreTagsOpen, setMoreTagsOpen] = useState(false);

  // Shared state
  const [problem, setProblem] = useState<FreePlayProblemInfo | null>(null);
  const [recommendTag, setRecommendTag] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");

  // ---- Tag toggle ----
  const toggleTag = useCallback((tag: string) => {
    setSelectedTags((prev) => {
      const next = new Set(prev);
      if (next.has(tag)) {
        next.delete(tag);
      } else {
        next.add(tag);
      }
      return next;
    });
  }, []);

  // ---- Manual search ----
  const handleSearch = useCallback(async () => {
    setLoading(true);
    setError("");
    setProblem(null);
    setRecommendTag(null);
    try {
      const res = await freePlayApi.freePlaySearch(
        minRating,
        maxRating,
        Array.from(selectedTags),
      );
      if (res.found && res.problem) {
        setProblem(res.problem);
      } else {
        setError(res.message || t("noProblemFound"));
      }
    } catch {
      setError(t("error.searchFailed"));
    } finally {
      setLoading(false);
    }
  }, [minRating, maxRating, selectedTags, t]);

  // ---- Adaptive recommend ----
  const handleRecommend = useCallback(async () => {
    setLoading(true);
    setError("");
    setProblem(null);
    setRecommendTag(null);
    try {
      const res = await freePlayApi.freePlayRecommend();
      if (res.found && res.problem) {
        setProblem(res.problem);
        setRecommendTag(res.recommended_tag);
      } else {
        setError(res.message || t("noProblemFound"));
      }
    } catch {
      setError(t("error.recommendFailed"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  // ---- Start session ----
  const handleStart = useCallback(async () => {
    if (!problem) return;
    setStarting(true);
    setError("");
    try {
      const res = await freePlayApi.freePlayStart({
        problem_contest_id: problem.contest_id,
        problem_index: problem.index,
        problem_rating: problem.rating ?? 1200,
        problem_tags: problem.tags,
        problem_name: problem.name,
      });
      navigate(`/free-play/session/${res.session_id}`, { state: { problem, started_at: res.started_at } });
    } catch {
      setError(t("error.startFailed"));
    } finally {
      setStarting(false);
    }
  }, [problem, navigate, t]);

  // ---- Slider handlers ----
  const handleMinSlider = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const val = sliderToRating(Number(e.target.value));
      if (val <= maxRating) setMinRating(val);
    },
    [maxRating],
  );

  const handleMaxSlider = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const val = sliderToRating(Number(e.target.value));
      if (val >= minRating) setMaxRating(val);
    },
    [minRating],
  );

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-foreground">{t("title")}</h1>
        <p className="mt-1 text-sm text-muted-foreground">{t("description")}</p>
      </div>

      {/* Tab switcher */}
      <div className="flex gap-1 rounded-lg border border-border bg-muted/50 p-1">
        <button
          onClick={() => setTab("manual")}
          className={`flex flex-1 items-center justify-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-colors ${
            tab === "manual"
              ? "bg-card text-foreground shadow-sm"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          <Filter className="size-4" />
          {t("tabs.manual")}
        </button>
        <button
          onClick={() => setTab("recommend")}
          className={`flex flex-1 items-center justify-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-colors ${
            tab === "recommend"
              ? "bg-card text-foreground shadow-sm"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          <Sparkles className="size-4" />
          {t("tabs.recommend")}
        </button>
      </div>

      {/* Error */}
      <AnimatePresence>
        {error && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive"
          >
            {error}
          </motion.div>
        )}
      </AnimatePresence>

      {/* Manual filter panel */}
      {tab === "manual" && (
        <div className="space-y-5">
          {/* Rating range */}
          <div className="rounded-xl border border-border bg-card p-5">
            <h3 className="text-sm font-semibold text-foreground">{t("ratingRange")}</h3>
            <div className="mt-4 space-y-3">
              {/* Min slider */}
              <div className="flex items-center gap-3">
                <span className="w-20 text-xs text-muted-foreground">{t("minRating")}</span>
                <input
                  type="range"
                  min={0}
                  max={100}
                  value={ratingToSlider(minRating)}
                  onChange={handleMinSlider}
                  className="flex-1 accent-primary"
                />
                <span
                  className="w-12 text-right text-sm font-bold"
                  style={{ color: getRatingColor(minRating) }}
                >
                  {minRating}
                </span>
              </div>
              {/* Max slider */}
              <div className="flex items-center gap-3">
                <span className="w-20 text-xs text-muted-foreground">{t("maxRating")}</span>
                <input
                  type="range"
                  min={0}
                  max={100}
                  value={ratingToSlider(maxRating)}
                  onChange={handleMaxSlider}
                  className="flex-1 accent-primary"
                />
                <span
                  className="w-12 text-right text-sm font-bold"
                  style={{ color: getRatingColor(maxRating) }}
                >
                  {maxRating}
                </span>
              </div>
            </div>
          </div>

          {/* Tags */}
          <div className="rounded-xl border border-border bg-card p-5">
            <h3 className="text-sm font-semibold text-foreground">{t("tags")}</h3>
            <div className="mt-3 flex flex-wrap gap-1.5">
              {PRESET_TAGS.map((tag) => (
                <TagChip
                  key={tag}
                  tag={tag}
                  selected={selectedTags.has(tag)}
                  onToggle={() => toggleTag(tag)}
                />
              ))}
              <button
                type="button"
                onClick={() => setMoreTagsOpen(true)}
                className="inline-flex items-center gap-1 rounded-full border border-dashed border-border px-3 py-1 text-xs font-medium text-muted-foreground transition-colors hover:border-primary/50 hover:text-primary"
              >
                <Plus className="size-3" />
                {t("moreTags")}
              </button>
            </div>
            {/* Show extra selected tags that are not in PRESET_TAGS */}
            {Array.from(selectedTags).filter((tag) => !PRESET_TAGS.includes(tag)).length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {Array.from(selectedTags)
                  .filter((tag) => !PRESET_TAGS.includes(tag))
                  .map((tag) => (
                    <TagChip
                      key={tag}
                      tag={tag}
                      selected
                      onToggle={() => toggleTag(tag)}
                    />
                  ))}
              </div>
            )}
          </div>

          {/* Search button */}
          <Button size="lg" onClick={handleSearch} disabled={loading} className="w-full">
            {loading ? (
              <>
                <Loader2 className="mr-2 size-4 animate-spin" />
                {t("searching")}
              </>
            ) : (
              <>
                <Search className="mr-2 size-4" />
                {t("searchProblems")}
              </>
            )}
          </Button>
        </div>
      )}

      {/* Recommend panel */}
      {tab === "recommend" && (
        <div className="space-y-5">
          <Button size="lg" onClick={handleRecommend} disabled={loading} className="w-full">
            {loading ? (
              <>
                <Loader2 className="mr-2 size-4 animate-spin" />
                {t("recommending")}
              </>
            ) : (
              <>
                <Compass className="mr-2 size-4" />
                {t("recommendProblem")}
              </>
            )}
          </Button>
        </div>
      )}

      {/* Problem card (shared by both tabs) */}
      <AnimatePresence>
        {problem && (
          <>
            {/* Recommendation reason */}
            {tab === "recommend" && recommendTag && (
              <motion.p
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="text-sm text-muted-foreground"
              >
                {t("recommendReason", { tag: recommendTag.toUpperCase(), elo: problem.rating ?? "-" })}
              </motion.p>
            )}
            <ProblemCard
              problem={problem}
              onStart={handleStart}
              starting={starting}
            />
          </>
        )}
      </AnimatePresence>

      {/* Loading spinner (full-page overlay for recommend) */}
      {loading && !problem && tab === "recommend" && (
        <LoadingSpinner text={t("recommending")} className="py-12" />
      )}

      {/* More Tags Dialog */}
      <MoreTagsDialog
        open={moreTagsOpen}
        onClose={() => setMoreTagsOpen(false)}
        selectedTags={selectedTags}
        onToggleTag={toggleTag}
      />
    </div>
  );
}
