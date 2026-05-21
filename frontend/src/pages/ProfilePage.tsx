import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import {
  User,
  Mail,
  Trophy,
  Star,
  Coins,
  Calendar,
  ExternalLink,
  Loader2,
  Save,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { useAuthStore } from "@/stores/auth";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { EloChart } from "@/components/charts/EloChart";
import { extractApiError, getRatingColor, getDifficultyLabelKey, formatDate } from "@/utils";
import { MedalBadge } from "@/components/medal";
import { MedalCabinet } from "@/components/medal";
import { SkillMedalWall } from "@/components/medal";
import api from "@/services/api";
import type {
  EloHistoryPoint,
  ApiResponse,
  UserSettingsData,
  MedalInfo,
  MedalStatsResponse,
  SkillMedalItem,
} from "@/types";

// ---------------------------------------------------------------------------
// Inner form component -- owns its own editing state, keyed by user.id
// ---------------------------------------------------------------------------

function ProfileForm({
  user,
  onSave,
}: {
  user: NonNullable<ReturnType<typeof useAuthStore.getState>["user"]>;
  onSave: (username: string, email: string) => Promise<void>;
}) {
  const { t } = useTranslation(["profile", "common"]);
  const [editing, setEditing] = useState(false);
  const [username, setUsername] = useState(user.username);
  const [email, setEmail] = useState(user.email);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const handleSave = async () => {
    setError("");
    setSuccess("");
    setLoading(true);
    try {
      await onSave(username, email);
      setSuccess(t("profile:profileUpdated"));
      setEditing(false);
    } catch (err) {
      setError(extractApiError(err, t("profile:failedUpdate")));
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-foreground">{t("profile:profile")}</h1>
        {!editing && (
          <Button variant="outline" size="sm" onClick={() => setEditing(true)}>
            {t("profile:editProfile")}
          </Button>
        )}
      </div>

      {error && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {error}
        </div>
      )}
      {success && (
        <div className="rounded-lg border border-green-500/30 bg-green-500/10 px-4 py-3 text-sm text-green-400">
          {success}
        </div>
      )}

      <div className="rounded-xl border border-border bg-card p-6">
        <div className="flex items-start gap-5">
          <div className="flex size-16 shrink-0 items-center justify-center rounded-full bg-primary/10">
            <User className="size-8 text-primary" />
          </div>
          <div className="flex-1 space-y-3">
            {editing ? (
              <div className="space-y-3">
                <div>
                  <label className="mb-1 block text-xs font-medium text-muted-foreground">
                    {t("profile:username")}
                  </label>
                  <input
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm text-foreground focus:border-primary focus:outline-none"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-muted-foreground">
                    {t("profile:email")}
                  </label>
                  <input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm text-foreground focus:border-primary focus:outline-none"
                  />
                </div>
                <div className="flex gap-2">
                  <Button size="sm" onClick={handleSave} disabled={loading}>
                    {loading ? (
                      <Loader2 className="mr-1.5 size-3.5 animate-spin" />
                    ) : (
                      <Save className="mr-1.5 size-3.5" />
                    )}
                    {t("common:save")}
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
                    {t("common:cancel")}
                  </Button>
                </div>
              </div>
            ) : (
              <>
                <div>
                  <h2 className="text-lg font-bold text-foreground">{user.username}</h2>
                  <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
                    <Mail className="size-3.5" />
                    {user.email}
                  </div>
                </div>
                <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
                  <Calendar className="size-3.5" />
                  {t("profile:joined", { date: formatDate(user.created_at) })}
                </div>
                {user.cf_handle && (
                  <div className="flex items-center gap-2">
                    <span className="text-sm text-muted-foreground">{t("profile:cfHandleLabel")}</span>
                    <span className="text-sm font-medium text-foreground">{user.cf_handle}</span>
                    {user.cf_handle_verified && (
                      <span className="rounded bg-green-500/10 px-1.5 py-0.5 text-[10px] font-medium text-green-400">
                        {t("profile:verified")}
                      </span>
                    )}
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function ProfilePage() {
  const navigate = useNavigate();
  const { user, fetchUser } = useAuthStore();
  const { t } = useTranslation(["profile", "common"]);

  const handleSave = async (username: string, email: string) => {
    const body: Record<string, string> = {};
    if (username !== user?.username) body.username = username;
    if (email !== user?.email) body.email = email;
    if (Object.keys(body).length === 0) return;
    await api.put("/auth/profile", body);
    await fetchUser();
  };

  const [eloHistory, setEloHistory] = useState<EloHistoryPoint[]>([]);
  const [eloLoading, setEloLoading] = useState(true);
  const [eloError, setEloError] = useState(false);

  // Medal system state
  const [displayMode, setDisplayMode] = useState<"medal" | "cf_tier">("medal");
  const [overallMedal, setOverallMedal] = useState<MedalInfo | null>(null);
  const [medalStats, setMedalStats] = useState<Record<string, Record<string, number>>>({});
  const [totalMedals, setTotalMedals] = useState(0);
  const [skillMedals, setSkillMedals] = useState<SkillMedalItem[]>([]);

  useEffect(() => {
    let cancelled = false;
    api
      .get<ApiResponse<EloHistoryPoint[]>>("/auth/elo-history")
      .then((res) => {
        if (!cancelled) {
          setEloHistory(res.data.data);
          setEloLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setEloError(true);
          setEloLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Fetch medal data
  useEffect(() => {
    api
      .get<ApiResponse<UserSettingsData>>("/auth/settings")
      .then((res) => setDisplayMode(res.data.data.display_mode))
      .catch(() => {});
    api
      .get<ApiResponse<{ elo: number; medal: MedalInfo }>>("/medal/overall")
      .then((res) => setOverallMedal(res.data.data.medal))
      .catch(() => {});
    api
      .get<ApiResponse<MedalStatsResponse>>("/medal/stats")
      .then((res) => {
        setMedalStats(res.data.data.stats);
        setTotalMedals(res.data.data.total_medals);
      })
      .catch(() => {});
    api
      .get<ApiResponse<{ skills: SkillMedalItem[] }>>("/medal/skills")
      .then((res) => setSkillMedals(res.data.data.skills))
      .catch(() => {});
  }, []);

  if (!user) {
    return <LoadingSpinner text={t("profile:loadingProfile")} className="py-20" />;
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      {/* Key on user.id so form resets when user data changes */}
      <ProfileForm key={user.id} user={user} onSave={handleSave} />

      {!user.cf_handle && (
        <div className="flex items-center justify-between rounded-xl border border-border bg-card px-5 py-4">
          <div>
            <p className="text-sm font-medium text-foreground">{t("profile:linkCF")}</p>
            <p className="text-xs text-muted-foreground">
              {t("profile:linkCFDesc")}
            </p>
          </div>
          <Button variant="outline" size="sm" onClick={() => navigate("/profile/cf-bind")}>
            <ExternalLink className="mr-1.5 size-3.5" />
            {t("profile:bindHandle")}
          </Button>
        </div>
      )}

      {/* Stats */}
      <div className="grid gap-4 sm:grid-cols-3">
        <div className="rounded-xl border border-border bg-card p-5">
          <div className="flex items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-lg bg-primary/10">
              <Trophy className="size-5 text-primary" />
            </div>
            <div>
              <p className="text-xs text-muted-foreground">{t("profile:eloRating")}</p>
              {displayMode === "medal" && overallMedal ? (
                <div className="flex items-center gap-2">
                  <span className="text-2xl font-bold" style={{ color: getRatingColor(user.elo) }}>
                    {user.elo}
                  </span>
                  <MedalBadge level={overallMedal.level} type={overallMedal.type} size="sm" />
                </div>
              ) : (
                <p className="text-2xl font-bold" style={{ color: getRatingColor(user.elo) }}>
                  {user.elo} <span className="text-sm font-medium">/ {t(getDifficultyLabelKey(user.elo))}</span>
                </p>
              )}
            </div>
          </div>
        </div>
        <div className="rounded-xl border border-border bg-card p-5">
          <div className="flex items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-lg bg-yellow-500/10">
              <Star className="size-5 text-yellow-400" />
            </div>
            <div>
              <p className="text-xs text-muted-foreground">{t("profile:performancePoints")}</p>
              <p className="text-2xl font-bold text-yellow-400">{user.pp}</p>
            </div>
          </div>
        </div>
        <div className="rounded-xl border border-border bg-card p-5">
          <div className="flex items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-lg bg-amber-500/10">
              <Coins className="size-5 text-amber-400" />
            </div>
            <div>
              <p className="text-xs text-muted-foreground">{t("common:tokens")}</p>
              <p className="text-2xl font-bold text-amber-400">{user.tokens}</p>
            </div>
          </div>
        </div>
      </div>

      {/* Elo History */}
      {eloLoading ? (
        <div className="rounded-xl border border-border bg-card p-5">
          <h3 className="mb-4 text-sm font-semibold text-foreground">{t("profile:eloTrend")}</h3>
          <div className="flex h-[220px] items-center justify-center">
            <LoadingSpinner />
          </div>
        </div>
      ) : eloError ? (
        <div className="rounded-xl border border-border bg-card p-5">
          <h3 className="mb-4 text-sm font-semibold text-foreground">{t("profile:eloTrend")}</h3>
          <div className="flex h-[220px] items-center justify-center text-sm text-muted-foreground">
            {t("profile:failedLoadElo")}
          </div>
        </div>
      ) : (
        <EloChart data={eloHistory} />
      )}

      {/* Medal Cabinet */}
      <MedalCabinet stats={medalStats} totalMedals={totalMedals} />

      {/* Skill Medal Wall */}
      <SkillMedalWall skills={skillMedals} />

      {/* PP Ranking Placeholder */}
      <div className="rounded-xl border border-border bg-card p-5">
        <h3 className="text-sm font-semibold text-foreground">{t("profile:ppRanking")}</h3>
        <p className="mt-2 text-sm text-muted-foreground">
          {t("profile:ppRankingDesc")}
        </p>
        <Button
          variant="outline"
          size="sm"
          className="mt-3"
          onClick={() => navigate("/leaderboard")}
        >
          {t("profile:viewLeaderboard")}
        </Button>
      </div>
    </div>
  );
}
