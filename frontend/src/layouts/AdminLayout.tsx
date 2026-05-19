import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { Settings, ArrowLeft, Shield } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAuthStore } from "@/stores/auth";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Admin navigation items
// ---------------------------------------------------------------------------

const adminNavItems = [
  { to: "/admin", label: "Overview", icon: Shield },
  { to: "/admin/config", label: "Configuration", icon: Settings },
];

// ---------------------------------------------------------------------------
// Admin layout
// ---------------------------------------------------------------------------

export function AdminLayout() {
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);

  return (
    <div className="flex min-h-screen bg-background">
      {/* Sidebar */}
      <aside className="hidden w-56 flex-col border-r border-border bg-card md:flex">
        {/* Brand */}
        <div className="flex h-14 items-center gap-2 border-b border-border px-4">
          <Shield className="size-5 text-primary" />
          <span className="text-lg font-bold text-foreground">Admin Panel</span>
        </div>

        {/* Nav */}
        <nav className="flex-1 space-y-1 px-3 py-4">
          {adminNavItems.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end
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
              {label}
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
            Back to App
          </Button>
        </div>
      </aside>

      {/* Main area */}
      <div className="flex flex-1 flex-col">
        <header className="flex h-14 items-center gap-4 border-b border-border bg-card px-4 md:px-6">
          <Link to="/admin" className="text-lg font-bold text-foreground md:hidden">
            Admin Panel
          </Link>
          <div className="text-sm text-muted-foreground">
            {user?.is_admin ? "Administrator" : "Unauthorized"}
          </div>
        </header>

        <main className="flex-1 overflow-y-auto p-4 lg:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
