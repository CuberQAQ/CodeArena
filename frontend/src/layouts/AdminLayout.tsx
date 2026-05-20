import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { Settings, ArrowLeft, Shield } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { useAuthStore } from "@/stores/auth";
import { cn } from "@/lib/utils";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";

// ---------------------------------------------------------------------------
// Admin navigation items
// ---------------------------------------------------------------------------

const adminNavItems = [
  { to: "/admin", labelKey: "nav:overview", icon: Shield, end: true },
  { to: "/admin/config", labelKey: "nav:configuration", icon: Settings, end: false },
];

// ---------------------------------------------------------------------------
// Admin layout
// ---------------------------------------------------------------------------

export function AdminLayout() {
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const { t } = useTranslation();

  return (
    <div className="flex min-h-screen bg-background">
      {/* Sidebar */}
      <aside className="hidden w-56 flex-col border-r border-border bg-card md:flex">
        {/* Brand */}
        <div className="flex h-14 items-center gap-2 border-b border-border px-4">
          <Shield className="size-5 text-primary" />
          <span className="text-lg font-bold text-foreground">{t("nav:adminPanel")}</span>
        </div>

        {/* Nav */}
        <nav className="flex-1 space-y-1 px-3 py-4">
          {adminNavItems.map(({ to, labelKey, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                  isActive
                    ? "bg-primary/10 text-primary"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )
              }
            >
              <Icon className="size-4" />
              {t(labelKey)}
            </NavLink>
          ))}
        </nav>

        {/* Back to main */}
        <div className="border-t border-border p-4">
          <div className="mb-2 text-sm font-medium text-foreground truncate">
            {user?.username ?? "Admin"}
          </div>
          <Button
            variant="ghost"
            size="sm"
            className="w-full justify-start gap-2"
            onClick={() => navigate("/dashboard")}
          >
            <ArrowLeft className="size-4" />
            {t("nav:backToApp")}
          </Button>
        </div>
      </aside>

      {/* Main area */}
      <div className="flex flex-1 flex-col">
        <header className="flex h-14 items-center gap-4 border-b border-border bg-card px-4 md:px-6">
          <Link to="/admin" className="text-lg font-bold text-foreground md:hidden">
            {t("nav:adminPanel")}
          </Link>
          <div className="text-sm text-muted-foreground">
            {user?.is_admin ? t("nav:administrator") : t("nav:unauthorized")}
          </div>
          <div className="ml-auto">
            <LanguageSwitcher />
          </div>
        </header>

        <main className="flex-1 overflow-y-auto p-4 lg:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
