import { useTranslation } from "react-i18next";

export function LanguageSwitcher() {
  const { i18n } = useTranslation();
  const isEn = i18n.language.startsWith("en");

  const toggle = () => {
    i18n.changeLanguage(isEn ? "zh" : "en");
  };

  return (
    <button
      onClick={toggle}
      className="rounded-md border border-border px-2 py-1 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
      title={isEn ? "Switch to Chinese" : "切换到英文"}
    >
      {isEn ? "EN / 中" : "EN / 中"}
    </button>
  );
}
