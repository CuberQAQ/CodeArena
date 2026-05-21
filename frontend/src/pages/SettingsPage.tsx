import { useEffect, useState } from "react";
import { Settings, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { extractApiError } from "@/utils";
import api from "@/services/api";
import type { ApiResponse, UserSettingsData } from "@/types";

export default function SettingsPage() {
  const { t } = useTranslation(["medal", "common"]);
  const [displayMode, setDisplayMode] = useState<"medal" | "cf_tier">("medal");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  useEffect(() => {
    api
      .get<ApiResponse<UserSettingsData>>("/auth/settings")
      .then((res) => {
        setDisplayMode(res.data.data.display_mode);
      })
      .catch(() => {
        // Default to medal mode if settings not found
        setDisplayMode("medal");
      })
      .finally(() => setLoading(false));
  }, []);

  const handleSave = async () => {
    setError("");
    setSuccess("");
    setSaving(true);
    try {
      await api.put("/auth/settings", { display_mode: displayMode });
      setSuccess(t("medal:settings.saved"));
    } catch (err) {
      setError(extractApiError(err, t("medal:settings.failedSave")));
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <LoadingSpinner text={t("common:loading")} className="py-20" />;
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div className="flex items-center gap-3">
        <div className="flex size-10 items-center justify-center rounded-lg bg-primary/10">
          <Settings className="size-5 text-primary" />
        </div>
        <div>
          <h1 className="text-2xl font-bold text-foreground">{t("medal:settings.title")}</h1>
        </div>
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

      {/* Display Mode Setting */}
      <div className="rounded-xl border border-border bg-card p-5">
        <h2 className="mb-4 text-sm font-semibold text-foreground">{t("medal:settings.displayMode")}</h2>

        <div className="space-y-3">
          {/* Medal Mode */}
          <label
            className={`flex cursor-pointer items-start gap-3 rounded-lg border p-4 transition-colors ${
              displayMode === "medal"
                ? "border-primary bg-primary/5"
                : "border-border hover:border-primary/30"
            }`}
          >
            <input
              type="radio"
              name="displayMode"
              value="medal"
              checked={displayMode === "medal"}
              onChange={() => setDisplayMode("medal")}
              className="mt-0.5 accent-primary"
            />
            <div>
              <p className="text-sm font-medium text-foreground">{t("medal:settings.medalMode")}</p>
              <p className="mt-0.5 text-xs text-muted-foreground">{t("medal:settings.medalModeDesc")}</p>
            </div>
          </label>

          {/* CF Tier Mode */}
          <label
            className={`flex cursor-pointer items-start gap-3 rounded-lg border p-4 transition-colors ${
              displayMode === "cf_tier"
                ? "border-primary bg-primary/5"
                : "border-border hover:border-primary/30"
            }`}
          >
            <input
              type="radio"
              name="displayMode"
              value="cf_tier"
              checked={displayMode === "cf_tier"}
              onChange={() => setDisplayMode("cf_tier")}
              className="mt-0.5 accent-primary"
            />
            <div>
              <p className="text-sm font-medium text-foreground">{t("medal:settings.cfTierMode")}</p>
              <p className="mt-0.5 text-xs text-muted-foreground">{t("medal:settings.cfTierModeDesc")}</p>
            </div>
          </label>
        </div>

        <div className="mt-4 flex justify-end">
          <Button onClick={handleSave} disabled={saving}>
            {saving ? (
              <Loader2 className="mr-1.5 size-3.5 animate-spin" />
            ) : (
              <Settings className="mr-1.5 size-3.5" />
            )}
            {t("common:save")}
          </Button>
        </div>
      </div>
    </div>
  );
}
