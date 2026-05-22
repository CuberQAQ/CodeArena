import { useState, useEffect, useCallback } from "react";
import { CalendarCheck, Gift, RotateCcw } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import api from "@/services/api";
import type { ApiResponse, CheckInStatusData, CheckInResponseData } from "@/types";

export function CheckInCard() {
  const { t } = useTranslation("dashboard");
  const [status, setStatus] = useState<CheckInStatusData | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchStatus = useCallback(async () => {
    try {
      const res = await api.get<ApiResponse<CheckInStatusData>>("/checkin/status");
      setStatus(res.data.data);
      setError(null);
    } catch {
      setError(t("checkin.errorLoad"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch initial check-in status
    fetchStatus();
  }, [fetchStatus]);

  const handleCheckIn = async () => {
    setActionLoading(true);
    setError(null);
    try {
      await api.post<ApiResponse<CheckInResponseData>>("/checkin");
      await fetchStatus();
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { message?: string } } })?.response?.data
          ?.message ?? t("checkin.errorCheckin");
      setError(msg);
    } finally {
      setActionLoading(false);
    }
  };

  const handleMakeup = async () => {
    setActionLoading(true);
    setError(null);
    try {
      await api.post<ApiResponse<CheckInResponseData>>("/checkin/makeup");
      await fetchStatus();
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { message?: string } } })?.response?.data
          ?.message ?? t("checkin.errorMakeup");
      setError(msg);
    } finally {
      setActionLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="rounded-xl border border-border bg-card p-5">
        <div className="animate-pulse space-y-3">
          <div className="h-4 w-24 rounded bg-muted" />
          <div className="h-8 w-full rounded bg-muted" />
        </div>
      </div>
    );
  }

  if (!status) return null;

  const canMakeup = status.can_makeup;

  // Build week display (current ISO week, Mon-Sun)
  const now = new Date();
  const dayOfWeek = now.getDay(); // 0=Sun, 1=Mon, ...
  const mondayOffset = dayOfWeek === 0 ? -6 : 1 - dayOfWeek;
  const monday = new Date(now);
  monday.setDate(now.getDate() + mondayOffset);

  const weekDays = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
  const todayIndex = dayOfWeek === 0 ? 6 : dayOfWeek - 1; // Mon=0 ... Sun=6

  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <div className="mb-3 flex items-center gap-2">
        <CalendarCheck className="size-5 text-emerald-400" />
        <h3 className="text-sm font-semibold text-foreground">
          {t("checkin.title")}
        </h3>
        {status.streak_days > 0 && (
          <span className="ml-auto rounded-full bg-emerald-500/10 px-2 py-0.5 text-xs font-medium text-emerald-400">
            {t("checkin.streakShort", { days: status.streak_days })}
          </span>
        )}
      </div>

      {/* Week dots */}
      <div className="mb-3 flex justify-between">
        {weekDays.map((day, idx) => {
          const isToday = idx === todayIndex;
          const dayDate = new Date(monday);
          dayDate.setDate(monday.getDate() + idx);
          const dayStr = dayDate.toISOString().split("T")[0];
          const checked = status.checked_dates_this_week?.includes(dayStr) ?? false;
          return (
            <div key={day} className="flex flex-col items-center gap-1">
              <div
                className={`flex size-7 items-center justify-center rounded-full text-xs font-medium transition-colors ${
                  checked
                    ? "bg-emerald-500/20 text-emerald-400"
                    : isToday
                      ? "border border-emerald-400/50 text-emerald-300"
                      : "bg-muted text-muted-foreground"
                }`}
              >
                {checked ? "✓" : ""}
              </div>
              <span className="text-[10px] text-muted-foreground">
                {t(`checkin.days.${day}`)}
              </span>
            </div>
          );
        })}
      </div>

      {/* Reward info */}
      <div className="mb-3 flex items-center gap-2 text-xs text-muted-foreground">
        <Gift className="size-3.5 text-amber-400" />
        {status.checked_in_today ? (
          <span>{t("checkin.alreadyCheckedIn")}</span>
        ) : (
          <span>{t("checkin.nextReward", { tokens: status.next_reward })}</span>
        )}
      </div>

      {/* Actions */}
      <div className="flex gap-2">
        {status.checked_in_today ? (
          <Button variant="outline" size="sm" disabled className="flex-1">
            <CalendarCheck className="size-3.5" />
            {t("checkin.checkedIn")}
          </Button>
        ) : (
          <Button
            size="sm"
            className="flex-1 bg-emerald-600 hover:bg-emerald-700"
            onClick={handleCheckIn}
            disabled={actionLoading}
          >
            <CalendarCheck className="size-3.5" />
            {t("checkin.checkin")}
          </Button>
        )}
        {canMakeup && (
          <Button
            variant="outline"
            size="sm"
            onClick={handleMakeup}
            disabled={actionLoading}
          >
            <RotateCcw className="size-3.5" />
            {t("checkin.makeup")}
          </Button>
        )}
      </div>

      {/* Make-up info */}
      <div className="mt-2 text-center text-[10px] text-muted-foreground">
        {t("checkin.makeupUsed", {
          used: status.makeup_used_this_week,
          limit: status.makeup_limit,
        })}
      </div>

      {/* Error */}
      {error && (
        <p className="mt-2 text-xs text-red-400">{error}</p>
      )}
    </div>
  );
}
