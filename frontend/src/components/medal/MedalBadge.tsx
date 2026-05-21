import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";

export interface MedalBadgeProps {
  level: string;
  type?: string;
  size?: "sm" | "md" | "lg";
  className?: string;
}

const MEDAL_COLORS: Record<string, string> = {
  gold: "#FFD700",
  silver: "#C0C0C0",
  bronze: "#CD7F32",
};

const SIZE_MAP = {
  sm: { circle: "size-4", text: "text-[10px]", icon: "text-[9px]" },
  md: { circle: "size-6", text: "text-xs", icon: "text-[11px]" },
  lg: { circle: "size-9", text: "text-sm", icon: "text-sm" },
};

const LEVEL_I18N_KEY: Record<string, string> = {
  world_finals: "medal:levels.worldFinals",
  ec_final: "medal:levels.ecFinal",
  regional: "medal:levels.regional",
  provincial: "medal:levels.provincial",
  unranked: "medal:levels.unranked",
};

const TYPE_ICON: Record<string, string> = {
  gold: "★",    // star
  silver: "★",
  bronze: "★",
};

export function MedalBadge({ level, type, size = "md", className }: MedalBadgeProps) {
  const { t } = useTranslation("medal");
  const s = SIZE_MAP[size];
  const isUnranked = !type || level === "unranked";

  if (isUnranked) {
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-muted-foreground",
          s.text,
          className,
        )}
      >
        {t("medal:levels.unranked")}
      </span>
    );
  }

  const color = MEDAL_COLORS[type] ?? "#9CA3AF";

  return (
    <span className={cn("inline-flex items-center gap-1.5", className)}>
      <span
        className={cn(
          "inline-flex items-center justify-center rounded-full font-bold",
          s.circle,
        )}
        style={{
          backgroundColor: `${color}20`,
          color,
          border: `2px solid ${color}`,
        }}
      >
        <span className={s.icon}>{TYPE_ICON[type] ?? ""}</span>
      </span>
      <span className={cn("font-medium", s.text)} style={{ color }}>
        {t(LEVEL_I18N_KEY[level] ?? level)} {t(`medal:types.${type}`)}
      </span>
    </span>
  );
}
