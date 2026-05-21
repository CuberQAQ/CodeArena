import { Sun, Moon, Monitor } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useTheme } from "@/hooks/useTheme";
import type { Theme } from "@/hooks/useTheme";

const themeIcon: Record<Theme, React.ElementType> = {
  light: Sun,
  dark: Moon,
  system: Monitor,
};

export function ThemeToggle() {
  const { theme, cycleTheme } = useTheme();
  const { t } = useTranslation("common");

  const Icon = themeIcon[theme];
  const label = t(`theme.${theme}`);

  return (
    <button
      type="button"
      onClick={cycleTheme}
      className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
      title={label}
      aria-label={label}
    >
      <Icon className="size-4" />
      <span className="hidden lg:inline">{label}</span>
    </button>
  );
}
