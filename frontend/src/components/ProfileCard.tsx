import { useRef, useState, useCallback } from "react";
import { Download, Loader2 } from "lucide-react";
import { toPng } from "html-to-image";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { getRatingColor, getDifficultyLabelKey } from "@/utils";
import type { MedalInfo, SkillMedalItem } from "@/types";

// ---------------------------------------------------------------------------
// CF tag -> topic slug mapping for i18n
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Medal color constants
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
  ppRank?: number | null;
}

// ---------------------------------------------------------------------------
// The visual card
// ---------------------------------------------------------------------------

function ProfileCardContent({ user, displayMode, overallMedal, totalMedals, skillMedals, totalSolved, streakDays, ppRank }: ProfileCardProps) {
  const { t } = useTranslation(["profile", "medal", "common", "rating", "training"]);

  const eloColor = getRatingColor(user.elo);

  // Build medal display text
  let medalText: string;
  let medalColor = eloColor;
  if (displayMode === "medal" && overallMedal && overallMedal.type) {
    medalColor = MEDAL_COLORS[overallMedal.type] ?? "#9CA3AF";
    medalText = `${MEDAL_TYPE_SYMBOLS[overallMedal.type]} ${t(`medal:levels.${levelToI18nKey(overallMedal.level)}`)} ${t(`medal:types.${overallMedal.type}`)}`;
  } else {
    const tierKey = getDifficultyLabelKey(user.elo);
    medalText = t(tierKey);
  }

  return (
    <div
      style={{
        width: 400,
        height: 533,
        background: "linear-gradient(160deg, #0c0e1a 0%, #141828 40%, #1a1040 100%)",
        borderRadius: 16,
        padding: 0,
        color: "#e2e8f0",
        fontFamily: "system-ui, -apple-system, sans-serif",
        position: "relative",
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
      }}
    >
      {/* Accent glow - top right, colored by Elo */}
      <div
        style={{
          position: "absolute",
          top: -60,
          right: -60,
          width: 200,
          height: 200,
          borderRadius: "50%",
          background: eloColor,
          filter: "blur(80px)",
          opacity: 0.15,
        }}
      />
      {/* Secondary glow - bottom left */}
      <div
        style={{
          position: "absolute",
          bottom: -40,
          left: -40,
          width: 140,
          height: 140,
          borderRadius: "50%",
          background: "#6366f1",
          filter: "blur(60px)",
          opacity: 0.08,
        }}
      />

      {/* Header bar */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "16px 20px 0",
        }}
      >
        <span
          style={{
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: 2,
            color: "#64748b",
            textTransform: "uppercase",
          }}
        >
          CODE ARENA
        </span>
        <div
          style={{
            height: 2,
            flex: 1,
            margin: "0 12px",
            background: `linear-gradient(90deg, transparent, ${eloColor}40, transparent)`,
          }}
        />
        {medalText && (
          <span style={{ fontSize: 10, fontWeight: 600, color: medalColor, whiteSpace: "nowrap" }}>
            {medalText}
          </span>
        )}
      </div>

      {/* Main content */}
      <div style={{ padding: "16px 20px 0", flex: 1, display: "flex", flexDirection: "column" }}>
        {/* Avatar + Name row */}
        <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 16 }}>
          <div
            style={{
              width: 48,
              height: 48,
              borderRadius: "50%",
              overflow: "hidden",
              backgroundColor: "#1e293b",
              flexShrink: 0,
              border: `2px solid ${eloColor}40`,
            }}
          >
            <img
              src={`/api/v1/auth/avatar/${user.id}`}
              alt=""
              style={{ width: 48, height: 48, objectFit: "cover" }}
              onError={(e) => {
                (e.target as HTMLImageElement).style.display = "none";
              }}
            />
          </div>
          <div style={{ minWidth: 0, flex: 1 }}>
            <div
              style={{
                fontSize: 20,
                fontWeight: 800,
                color: "#f8fafc",
                lineHeight: 1.2,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              {user.username}
            </div>
            {user.cf_handle && (
              <div style={{ fontSize: 11, color: "#64748b", marginTop: 1 }}>
                CF: {user.cf_handle}
              </div>
            )}
          </div>
        </div>

        {/* Elo centerpiece */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 16,
            padding: "16px 0",
            marginBottom: 12,
          }}
        >
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
            <span style={{ fontSize: 10, color: "#475569", fontWeight: 600, letterSpacing: 1, textTransform: "uppercase" }}>
              {t("profile:eloRating")}
            </span>
            <span style={{ fontSize: 36, fontWeight: 900, color: eloColor, lineHeight: 1.1 }}>
              {user.elo}
            </span>
          </div>
          <div style={{ width: 1, height: 40, background: "rgba(71, 85, 105, 0.25)" }} />
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
            <span style={{ fontSize: 10, color: "#475569", fontWeight: 600, letterSpacing: 1, textTransform: "uppercase" }}>
              PP
            </span>
            <span style={{ fontSize: 36, fontWeight: 900, color: "#facc15", lineHeight: 1.1 }}>
              {user.pp}
            </span>
            {ppRank != null && (
              <span style={{ fontSize: 10, color: "#64748b", marginTop: 1 }}>#{ppRank}</span>
            )}
          </div>
          <div style={{ width: 1, height: 40, background: "rgba(71, 85, 105, 0.25)" }} />
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
            <span style={{ fontSize: 10, color: "#475569", fontWeight: 600, letterSpacing: 1, textTransform: "uppercase" }}>
              {t("medal:cabinet.title")}
            </span>
            <span style={{ fontSize: 36, fontWeight: 900, color: "#f8fafc", lineHeight: 1.1 }}>
              {totalMedals}
            </span>
          </div>
        </div>

        {/* Stats row */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: 8,
            marginBottom: 12,
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              padding: "8px 12px",
              borderRadius: 8,
              background: "rgba(30, 41, 59, 0.5)",
              border: "1px solid rgba(71, 85, 105, 0.15)",
            }}
          >
            <span style={{ fontSize: 11, color: "#64748b" }}>{t("profile:cardSolved")}</span>
            <span style={{ fontSize: 14, fontWeight: 700, color: "#34d399" }}>{totalSolved}</span>
          </div>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              padding: "8px 12px",
              borderRadius: 8,
              background: "rgba(30, 41, 59, 0.5)",
              border: "1px solid rgba(71, 85, 105, 0.15)",
            }}
          >
            <span style={{ fontSize: 11, color: "#64748b" }}>{t("profile:cardCheckins")}</span>
            <span style={{ fontSize: 14, fontWeight: 700, color: "#fb923c" }}>{streakDays}</span>
          </div>
        </div>

        {/* Skill Medals */}
        {skillMedals.length > 0 && (
          <div style={{ flex: 1, minHeight: 0 }}>
            <div
              style={{
                fontSize: 9,
                color: "#475569",
                fontWeight: 600,
                textTransform: "uppercase",
                letterSpacing: 0.8,
                marginBottom: 6,
              }}
            >
              {t("profile:cardSkillMedals")}
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
              {skillMedals.map((skill) => {
                const mType = skill.type;
                if (!mType) {
                  const slug = CF_TAG_TO_SLUG[skill.tag];
                  return (
                    <span
                      key={skill.tag}
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        padding: "2px 7px",
                        borderRadius: 4,
                        backgroundColor: "rgba(30, 41, 59, 0.6)",
                        fontSize: 9,
                        color: "#64748b",
                      }}
                    >
                      {slug ? t(`training:topic.${slug}`) : skill.tag}
                    </span>
                  );
                }
                const color = MEDAL_COLORS[mType] ?? "#9CA3AF";
                const slug = CF_TAG_TO_SLUG[skill.tag];
                return (
                  <span
                    key={skill.tag}
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 3,
                      padding: "2px 7px",
                      borderRadius: 4,
                      backgroundColor: `${color}12`,
                      border: `1px solid ${color}30`,
                      fontSize: 9,
                      fontWeight: 600,
                      color,
                    }}
                  >
                    <span style={{ fontSize: 8 }}>{MEDAL_TYPE_SYMBOLS[mType]}</span>
                    {slug ? t(`training:topic.${slug}`) : skill.tag}
                  </span>
                );
              })}
            </div>
          </div>
        )}
      </div>

      {/* Footer */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: "0 20px 14px",
          gap: 8,
        }}
      >
        <div style={{ height: 1, flex: 1, background: "rgba(71, 85, 105, 0.15)" }} />
        <span style={{ fontSize: 8, color: "#334155", letterSpacing: 1.5, fontWeight: 600 }}>
          CODE-ARENA
        </span>
        <div style={{ height: 1, flex: 1, background: "rgba(71, 85, 105, 0.15)" }} />
      </div>
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
// Helper
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
