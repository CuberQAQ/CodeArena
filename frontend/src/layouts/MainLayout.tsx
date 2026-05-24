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
  Clock,
} from "lucide-react";
import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { useAuthStore } from "@/stores/auth";
import { cn } from "@/lib/utils";
import { Avatar } from "@/components/Avatar";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { ThemeToggle } from "@/components/ThemeToggle";
import { MedalBadge } from "@/components/medal/MedalBadge";
import { getRatingColor, ratingToMedal } from "@/utils";

// ---------------------------------------------------------------------------
// Navigation items
// ---------------------------------------------------------------------------

const navItems = [
  { to: "/dashboard", labelKey: "nav:dashboard", icon: Home },
  { to: "/challenge", labelKey: "nav:challenge", icon: Swords },
  { to: "/free-play", labelKey: "nav:freePlay", icon: Compass },
  { to: "/training", labelKey: "nav:training", icon: Dumbbell },
  { to: "/contest", labelKey: "nav:contest", icon: Trophy },
  { to: "/ranking", labelKey: "nav:ranking", icon: BarChart3 },
  { to: "/profile", labelKey: "nav:profile", icon: User },
  { to: "/settings", labelKey: "nav:settings", icon: Settings },
];

// ---------------------------------------------------------------------------
// Online time hook
// ---------------------------------------------------------------------------

function useOnlineTime(loginTime: string | null): string {
  const calcElapsed = useCallback((): string => {
    if (!loginTime) return "00:00:00";
    const login = new Date(loginTime).getTime();
    const now = Date.now();
    let diff = Math.max(0, Math.floor((now - login) / 1000));
    const h = Math.floor(diff / 3600);
    diff %= 3600;
    const m = Math.floor(diff / 60);
    const s = diff % 60;
    return `${h.toString().padStart(2, "0")}:${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
  }, [loginTime]);

  const [elapsed, setElapsed] = useState(calcElapsed);

  useEffect(() => {
    setElapsed(calcElapsed());
    const id = setInterval(() => setElapsed(calcElapsed()), 1000);
    return () => clearInterval(id);
  }, [calcElapsed]);

  return elapsed;
}

// ---------------------------------------------------------------------------
// PlayerInfoBar (desktop top bar center-right)
// ---------------------------------------------------------------------------

function PlayerInfoBar() {
  const { t } = useTranslation("nav");
  const user = useAuthStore((s) => s.user);
  const loginTime = useAuthStore((s) => s.loginTime);
  const onlineTime = useOnlineTime(loginTime);

  if (!user) return null;

  const elo = user.elo ?? 1200;
  const eloColor = getRatingColor(elo);
  const medal = ratingToMedal(elo);

  return (
    <div className="flex items-center gap-2">
      {/* Desktop: full info */}
      <div className="hidden lg:flex items-center gap-3">
        <Avatar userId={user.id} size={32} />
        <span className="text-sm font-medium text-foreground truncate max-w-[120px]">
          {user.username}
        </span>
        <span className="text-sm font-bold" style={{ color: eloColor }}>
          {elo}
        </span>
        <MedalBadge level={medal.level} type={medal.type} size="sm" />
        <span className="text-sm text-muted-foreground">
          {t("common:pp")}: {user.pp?.toFixed(1) ?? "0.0"}
        </span>
        <div className="flex items-center gap-1 text-xs text-muted-foreground">
          <Clock className="size-3" />
          <span className="font-mono tabular-nums">{onlineTime}</span>
        </div>
      </div>

      {/* Mobile: compact -- Avatar + Elo + online time */}
      <div className="flex items-center gap-2 lg:hidden">
        <Avatar userId={user.id} size={28} />
        <span className="text-sm font-bold" style={{ color: eloColor }}>
          {elo}
        </span>
        <div className="flex items-center gap-1 text-xs text-muted-foreground">
          <Clock className="size-3" />
          <span className="font-mono tabular-nums">{onlineTime}</span>
        </div>
      </div>
    </div>
  );
}

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
          <div className="mb-2 flex items-center gap-2 text-sm font-medium text-foreground">
            <Avatar userId={user?.id} size={36} />
            <span className="truncate">{user?.username ?? t("profile")}</span>
          </div>
          <div className="mb-3 text-xs text-muted-foreground">
            {t("nav:eloTokens", { elo: user?.elo ?? 1200, tokens: user?.tokens ?? 0 })}
          </div>
          <ThemeToggle />
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
        {/* Top bar */}
        <header className="flex h-14 items-center gap-4 border-b border-border bg-card px-4 lg:px-6">
          {/* Mobile: hamburger + brand */}
          <button
            className="rounded-md p-1 text-muted-foreground hover:text-foreground lg:hidden"
            onClick={() => setSidebarOpen(true)}
          >
            <Menu className="size-5" />
          </button>
          <Link to="/dashboard" className="text-lg font-bold text-foreground lg:hidden">
            {t("nav:brand")}
          </Link>

          {/* Desktop: spacer to push player info center-right */}
          <div className="hidden lg:block" />

          {/* Player info bar */}
          <div className="ml-auto lg:ml-0">
            <PlayerInfoBar />
          </div>

          {/* Theme toggle + language switcher (far right) */}
          <div className="hidden lg:flex items-center gap-1">
            <ThemeToggle />
            <LanguageSwitcher />
          </div>

          {/* Mobile: only language switcher */}
          <div className="flex items-center gap-1 lg:hidden">
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
