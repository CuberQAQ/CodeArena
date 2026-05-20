import { Outlet } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";

/**
 * Centered card layout for login / register pages.
 */
export function AuthLayout() {
  const { t } = useTranslation("auth");

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <div className="w-full max-w-md">
        <div className="mb-8 text-center">
          <div className="flex items-center justify-center gap-3 mb-2">
            <h1 className="text-3xl font-bold tracking-tight text-foreground">Code Arena</h1>
            <LanguageSwitcher />
          </div>
          <p className="mt-2 text-sm text-muted-foreground">
            {t("platformSlogan")}
          </p>
        </div>
        <div className="rounded-xl border border-border bg-card p-6 shadow-sm">
          <Outlet />
        </div>
      </div>
    </div>
  );
}
