import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import { MedalBadge } from "./MedalBadge";

export interface SkillMedalItem {
  tag: string;
  level: string;
  type?: string;
  melo?: number;
}

export interface SkillMedalWallProps {
  skills: SkillMedalItem[];
  className?: string;
}

export function SkillMedalWall({ skills, className }: SkillMedalWallProps) {
  const { t } = useTranslation("medal");

  if (skills.length === 0) {
    return (
      <div className={cn("rounded-xl border border-border bg-card p-5", className)}>
        <h3 className="mb-3 text-sm font-semibold text-foreground">{t("skills.title")}</h3>
        <p className="text-sm text-muted-foreground">{t("skills.noSkills")}</p>
      </div>
    );
  }

  return (
    <div className={cn("rounded-xl border border-border bg-card p-5", className)}>
      <h3 className="mb-4 text-sm font-semibold text-foreground">{t("skills.title")}</h3>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {skills.map((skill) => (
          <div
            key={skill.tag}
            className="flex items-center justify-between rounded-lg border border-border/50 bg-background px-3 py-2"
          >
            <span className="text-xs font-medium text-foreground uppercase">
              {skill.tag}
            </span>
            <MedalBadge
              level={skill.level}
              type={skill.type}
              size="sm"
            />
          </div>
        ))}
      </div>
    </div>
  );
}
