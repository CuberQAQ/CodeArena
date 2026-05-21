import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";

export interface MedalCabinetProps {
  stats: Record<string, Record<string, number>>;
  totalMedals?: number;
  className?: string;
}

const LEVEL_ORDER = ["world_finals", "ec_final", "regional", "provincial"];
const TYPE_ORDER = ["gold", "silver", "bronze"];
const TYPE_COLORS: Record<string, string> = {
  gold: "#FFD700",
  silver: "#C0C0C0",
  bronze: "#CD7F32",
};

const LEVEL_I18N_KEY: Record<string, string> = {
  world_finals: "medal:levels.worldFinals",
  ec_final: "medal:levels.ecFinal",
  regional: "medal:levels.regional",
  provincial: "medal:levels.provincial",
};

export function MedalCabinet({ stats, totalMedals, className }: MedalCabinetProps) {
  const { t } = useTranslation("medal");

  const hasMedals = Object.keys(stats).length > 0;

  if (!hasMedals) {
    return (
      <div className={cn("rounded-xl border border-border bg-card p-5", className)}>
        <h3 className="mb-3 text-sm font-semibold text-foreground">{t("cabinet.title")}</h3>
        <p className="text-sm text-muted-foreground">{t("cabinet.noMedals")}</p>
      </div>
    );
  }

  return (
    <div className={cn("rounded-xl border border-border bg-card p-5", className)}>
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-foreground">{t("cabinet.title")}</h3>
        {totalMedals != null && (
          <span className="text-xs text-muted-foreground">
            {t("cabinet.totalMedals")}: {totalMedals}
          </span>
        )}
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-xs text-muted-foreground">
              <th className="pb-2 text-left font-medium">{t("cabinet.level")}</th>
              {TYPE_ORDER.map((type) => (
                <th key={type} className="pb-2 text-center font-medium">
                  <span style={{ color: TYPE_COLORS[type] }}>
                    {t(`cabinet.${type}`)}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {LEVEL_ORDER.map((level) => {
              const levelStats = stats[level];
              if (!levelStats) return null;
              return (
                <tr key={level} className="border-b border-border/50 last:border-0">
                  <td className="py-2 font-medium text-foreground">
                    {t(LEVEL_I18N_KEY[level] ?? level)}
                  </td>
                  {TYPE_ORDER.map((type) => {
                    const count = levelStats[type] ?? 0;
                    return (
                      <td key={type} className="py-2 text-center">
                        {count > 0 ? (
                          <span
                            className="inline-flex size-7 items-center justify-center rounded-full text-xs font-bold"
                            style={{
                              backgroundColor: `${TYPE_COLORS[type]}20`,
                              color: TYPE_COLORS[type],
                              border: `1.5px solid ${TYPE_COLORS[type]}`,
                            }}
                          >
                            {count}
                          </span>
                        ) : (
                          <span className="text-muted-foreground/30">-</span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
