import { useRef, useState, useCallback } from "react";
import { Download, Loader2 } from "lucide-react";
import { toPng } from "html-to-image";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { getRatingColor, getDifficultyLabelKey } from "@/utils";
import type { MedalInfo, SkillMedalItem } from "@/types";

// ---------------------------------------------------------------------------
// Medal color constants (same as MedalBadge)
// ---------------------------------------------------------------------------

const MEDAL_COLORS: Record<string, string> = {
  gold: "#FFD700",
  silver: "#C0C0C0",
  bronze: "#CD7F32",
};

const MEDAL_TYPE_SYMBOLS: Record<string, string> = {
  gold: "★",
  silver: "★",
  bronze: "★",
};

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface ProfileCardProps {
  user: {
    id: string;
    username: string;
    cf_handle: string | null;
    elo: number;
    pp: number;
    avatar_path?: string | null;
  };
  displayMode: "medal" | "cf_tier";
  overallMedal: MedalInfo | null;
  totalMedals: number;
  skillMedals: SkillMedalItem[];
  totalSolved: number;
  streakDays: number;
  /** PP rank, if available */
  ppRank?: number | null;
}

// ---------------------------------------------------------------------------
// The visual card (rendered off-screen for html2canvas capture)
// ---------------------------------------------------------------------------

function ProfileCardContent({ user, displayMode, overallMedal, totalMedals, skillMedals, totalSolved, streakDays, ppRank }: ProfileCardProps) {
  const { t } = useTranslation(["profile", "medal", "common", "rating"]);

  const eloColor = getRatingColor(user.elo);

  // Build medal display
  let medalDisplay: React.ReactNode;
  if (displayMode === "medal" && overallMedal && overallMedal.type) {
    const color = MEDAL_COLORS[overallMedal.type] ?? "#9CA3AF";
    medalDisplay = (
      <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
        <span
          style={{
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            width: 28,
            height: 28,
            borderRadius: "50%",
            backgroundColor: `${color}20`,
            color,
            border: `2px solid ${color}`,
            fontWeight: 700,
            fontSize: 14,
          }}
        >
          {MEDAL_TYPE_SYMBOLS[overallMedal.type] ?? ""}
        </span>
        <span style={{ color, fontWeight: 600, fontSize: 13 }}>
          {t(`medal:levels.${levelToI18nKey(overallMedal.level)}`)} {t(`medal:types.${overallMedal.type}`)}
        </span>
      </span>
    );
  } else {
    // CF tier mode
    const tierKey = getDifficultyLabelKey(user.elo);
    medalDisplay = (
      <span style={{ color: eloColor, fontWeight: 600, fontSize: 13 }}>
        {t(tierKey)}
      </span>
    );
  }

  return (
    <div
      style={{
        width: 400,
        height: 533,
        background: "linear-gradient(135deg, #0f172a 0%, #1e293b 100%)",
        borderRadius: 16,
        padding: 24,
        color: "#e2e8f0",
        fontFamily: "system-ui, -apple-system, sans-serif",
        position: "relative",
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
      }}
    >
      {/* Subtle decorative circle */}
      <div
        style={{
          position: "absolute",
          top: -40,
          right: -40,
          width: 120,
          height: 120,
          borderRadius: "50%",
          background: "rgba(99, 102, 241, 0.08)",
        }}
      />

      {/* Title */}
      <div
        style={{
          fontSize: 11,
          fontWeight: 600,
          textTransform: "uppercase" as const,
          letterSpacing: 1.5,
          color: "#64748b",
          marginBottom: 16,
        }}
      >
        {t("profile:cardTitle")}
      </div>

      {/* Top section: Avatar + Name + CF Handle */}
      <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 20 }}>
        <div
          style={{
            width: 56,
            height: 56,
            borderRadius: "50%",
            overflow: "hidden",
            backgroundColor: "#334155",
            flexShrink: 0,
          }}
        >
          {/* Inline avatar for export -- use img directly */}
          <img
            src={`/api/v1/auth/avatar/${user.id}`}
            alt=""
            style={{ width: 56, height: 56, objectFit: "cover" }}
            onError={(e) => {
              // Hide on error, show placeholder bg
              (e.target as HTMLImageElement).style.display = "none";
            }}
          />
        </div>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div
            style={{
              fontSize: 18,
              fontWeight: 700,
              color: "#f1f5f9",
              lineHeight: 1.2,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {user.username}
          </div>
          {user.cf_handle && (
            <div style={{ fontSize: 12, color: "#94a3b8", marginTop: 2 }}>
              CF: {user.cf_handle}
            </div>
          )}
        </div>
      </div>

      {/* Middle section: Medal/Tier + Elo + PP */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "12px 16px",
          backgroundColor: "rgba(30, 41, 59, 0.8)",
          borderRadius: 10,
          border: "1px solid rgba(71, 85, 105, 0.3)",
          marginBottom: 16,
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 4 }}>
          <div style={{ fontSize: 10, color: "#64748b", fontWeight: 500, textTransform: "uppercase", letterSpacing: 0.5 }}>
            {t("profile:eloRating")}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ fontSize: 22, fontWeight: 700, color: eloColor }}>{user.elo}</span>
            {medalDisplay}
          </div>
        </div>
        <div style={{ width: 1, height: 36, backgroundColor: "rgba(71, 85, 105, 0.3)" }} />
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 4 }}>
          <div style={{ fontSize: 10, color: "#64748b", fontWeight: 500, textTransform: "uppercase", letterSpacing: 0.5 }}>
            {t("profile:performancePoints")}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ fontSize: 22, fontWeight: 700, color: "#facc15" }}>{user.pp}</span>
            {ppRank != null && (
              <span style={{ fontSize: 11, color: "#94a3b8" }}>#{ppRank}</span>
            )}
          </div>
        </div>
        <div style={{ width: 1, height: 36, backgroundColor: "rgba(71, 85, 105, 0.3)" }} />
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 4 }}>
          <div style={{ fontSize: 10, color: "#64748b", fontWeight: 500, textTransform: "uppercase", letterSpacing: 0.5 }}>
            {t("medal:cabinet.title")}
          </div>
          <span style={{ fontSize: 22, fontWeight: 700, color: "#f1f5f9" }}>{totalMedals}</span>
        </div>
      </div>

      {/* Stats row: Solved + Check-in Days */}
      <div
        style={{
          display: "flex",
          gap: 12,
          marginBottom: 16,
        }}
      >
        <div
          style={{
            flex: 1,
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "8px 12px",
            backgroundColor: "rgba(30, 41, 59, 0.6)",
            borderRadius: 8,
            border: "1px solid rgba(71, 85, 105, 0.2)",
          }}
        >
          <span style={{ fontSize: 11, color: "#64748b" }}>{t("profile:cardSolved")}</span>
          <span style={{ fontSize: 15, fontWeight: 700, color: "#34d399", marginLeft: "auto" }}>{totalSolved}</span>
        </div>
        <div
          style={{
            flex: 1,
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "8px 12px",
            backgroundColor: "rgba(30, 41, 59, 0.6)",
            borderRadius: 8,
            border: "1px solid rgba(71, 85, 105, 0.2)",
          }}
        >
          <span style={{ fontSize: 11, color: "#64748b" }}>{t("profile:cardCheckins")}</span>
          <span style={{ fontSize: 15, fontWeight: 700, color: "#fb923c", marginLeft: "auto" }}>{streakDays}</span>
        </div>
      </div>

      {/* Skill Medal Overview */}
      {skillMedals.length > 0 && (
        <div style={{ marginBottom: 0, flex: 1, minHeight: 0 }}>
          <div
            style={{
              fontSize: 10,
              color: "#64748b",
              fontWeight: 600,
              textTransform: "uppercase",
              letterSpacing: 0.5,
              marginBottom: 8,
            }}
          >
            {t("profile:cardSkillMedals")}
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            {skillMedals.map((skill) => {
              const mType = skill.type;
              if (!mType) {
                return (
                  <span
                    key={skill.tag}
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 4,
                      padding: "3px 8px",
                      borderRadius: 6,
                      backgroundColor: "rgba(51, 65, 85, 0.6)",
                      fontSize: 10,
                      color: "#94a3b8",
                    }}
                  >
                    {skill.tag}
                  </span>
                );
              }
              const color = MEDAL_COLORS[mType] ?? "#9CA3AF";
              return (
                <span
                  key={skill.tag}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 4,
                    padding: "3px 8px",
                    borderRadius: 6,
                    backgroundColor: `${color}15`,
                    border: `1px solid ${color}40`,
                    fontSize: 10,
                    fontWeight: 500,
                    color,
                  }}
                >
                  <span style={{ fontSize: 9 }}>{MEDAL_TYPE_SYMBOLS[mType]}</span>
                  {skill.tag}
                </span>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Export button wrapper
// ---------------------------------------------------------------------------

export function ProfileCardExport(props: ProfileCardProps) {
  const { t } = useTranslation("profile");
  const cardRef = useRef<HTMLDivElement>(null);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleExport = useCallback(async () => {
    if (!cardRef.current || exporting) return;
    setExporting(true);
    setError(null);

    try {
      const dataUrl = await toPng(cardRef.current, {
        pixelRatio: 2,
        cacheBust: true,
      });

      const link = document.createElement("a");
      link.download = `code-arena-${props.user.username}.png`;
      link.href = dataUrl;
      link.click();
    } catch (err) {
      console.error("Profile card export failed:", err);
      setError(t("exportFailed"));
    } finally {
      setExporting(false);
    }
  }, [exporting, props.user.username, t]);

  return (
    <div>
      {/* Hidden render target for html2canvas */}
      <div
        aria-hidden
        style={{
          position: "fixed",
          left: "-9999px",
          top: 0,
        }}
      >
        <div ref={cardRef}>
          <ProfileCardContent {...props} />
        </div>
      </div>

      {/* Export button */}
      <Button
        variant="outline"
        size="sm"
        onClick={handleExport}
        disabled={exporting}
      >
        {exporting ? (
          <Loader2 className="mr-1.5 size-3.5 animate-spin" />
        ) : (
          <Download className="mr-1.5 size-3.5" />
        )}
        {exporting ? t("exporting") : t("exportCard")}
      </Button>

      {error && (
        <p className="mt-1.5 text-xs text-destructive">{error}</p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helper: convert medal level to i18n key suffix
// ---------------------------------------------------------------------------

function levelToI18nKey(level: string): string {
  const map: Record<string, string> = {
    world_finals: "worldFinals",
    ec_final: "ecFinal",
    regional: "regional",
    provincial: "provincial",
    unranked: "unranked",
  };
  return map[level] ?? level;
}
