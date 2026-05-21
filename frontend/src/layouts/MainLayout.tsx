import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import {
  Swords,
  Dumbbell,
  Trophy,
  User,
  BarChart3,
  LogOut,
  Menu,
  X,
  Home,
  Compass,
  Settings,
} from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { useAuthStore } from "@/stores/auth";
import { cn } from "@/lib/utils";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";

// ---------------------------------------------------------------------------
// Navigation items
// ---------------------------------------------------------------------------

const navItems = [
  { to: "/dashboard", labelKey: "nav:dashboard", icon: Home },
  { to: "/challenge", labelKey: "nav:challenge", icon: Swords },
  { to: "/free-play", labelKey: "nav:freePlay", icon: Compass },
  { to: "/training", labelKey: "nav:training", icon: Dumbbell },
  { to: "/contest", labelKey: "nav:contest", icon: Trophy },
  { to: "/leaderboard", labelKey: "nav:leaderboard", icon: BarChart3 },
  { to: "/profile", labelKey: "nav:profile", icon: User },
  { to: "/settings", labelKey: "nav:settings", icon: Settings },
];

// ---------------------------------------------------------------------------
// Sidebar
// ---------------------------------------------------------------------------

function Sidebar({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate();
  const logout = useAuthStore((s) => s.logout);
  const user = useAuthStore((s) => s.user);
  const { t } = useTranslation();

  const handleLogout = () => {
    logout();
    navigate("/");
  };

  return (
    <>
      {/* Mobile overlay */}
      {open && (
        <div
          className="fixed inset-0 z-30 bg-black/50 lg:hidden"
          onClick={onClose}
        />
      )}

      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-40 flex w-60 flex-col border-r border-border bg-card transition-transform lg:static lg:translate-x-0",
          open ? "translate-x-0" : "-translate-x-full",
        )}
      >
        {/* Logo / Brand */}
        <div className="flex h-14 items-center gap-2 border-b border-border px-4">
          <Swords className="size-5 text-primary" />
          <span className="text-lg font-bold text-foreground">{t("nav:brand")}</span>
          <button
            className="ml-auto rounded-md p-1 text-muted-foreground hover:text-foreground lg:hidden"
            onClick={onClose}
          >
            <X className="size-5" />
          </button>
        </div>

        {/* Navigation links */}
        <nav className="flex-1 space-y-1 px-3 py-4">
          {navItems.map(({ to, labelKey, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              onClick={onClose}
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

        {/* User info & logout */}
        <div className="border-t border-border p-4">
          <div className="mb-2 text-sm font-medium text-foreground truncate">
            {user?.username ?? t("profile")}
          </div>
          <div className="mb-3 text-xs text-muted-foreground">
            {t("nav:eloTokens", { elo: user?.elo ?? 1200, tokens: user?.tokens ?? 0 })}
          </div>
          <Button variant="ghost" size="sm" className="w-full justify-start gap-2" onClick={handleLogout}>
            <LogOut className="size-4" />
            {t("nav:logout")}
          </Button>
        </div>
      </aside>
    </>
  );
}

// ---------------------------------------------------------------------------
// Main layout
// ---------------------------------------------------------------------------

export function MainLayout() {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const { t } = useTranslation();

  return (
    <div className="flex min-h-screen bg-background">
      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />

      <div className="flex flex-1 flex-col">
        {/* Top bar (mobile hamburger) */}
        <header className="flex h-14 items-center gap-4 border-b border-border bg-card px-4 lg:px-6">
          <button
            className="rounded-md p-1 text-muted-foreground hover:text-foreground lg:hidden"
            onClick={() => setSidebarOpen(true)}
          >
            <Menu className="size-5" />
          </button>
          <Link to="/dashboard" className="text-lg font-bold text-foreground lg:hidden">
            {t("nav:brand")}
          </Link>
          <div className="ml-auto">
            <LanguageSwitcher />
          </div>
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-y-auto p-4 lg:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
