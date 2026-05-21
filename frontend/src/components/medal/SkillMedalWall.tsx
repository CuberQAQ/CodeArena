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

/** Map CF tag names to training locale topic slug keys. */
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

export function SkillMedalWall({ skills, className }: SkillMedalWallProps) {
  const { t } = useTranslation(["medal", "training"]);

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
              {CF_TAG_TO_SLUG[skill.tag]
                ? t(`training:topic.${CF_TAG_TO_SLUG[skill.tag]}`)
                : skill.tag}
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
