import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  Settings,
  Users,
  Activity,
  Sword,
  Dumbbell,
  Trophy,
  Search,
  ChevronLeft,
  ChevronRight,
  Shield,
  ShieldOff,
  UserCheck,
  UserX,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { extractApiError } from "@/utils";
import api from "@/services/api";
import type { ApiResponse } from "@/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface SystemStats {
  users: { total: number; active: number };
  challenges: { total: number; active: number };
  training: { total_sessions: number; active_sessions: number };
  contests: { total: number; active: number };
}

interface UserItem {
  id: string;
  username: string;
  email: string;
  elo: number;
  pp: number;
  tokens: number;
  is_active: boolean;
  is_admin: boolean;
  created_at: string | null;
  last_login_at: string | null;
}

interface UserListResponse {
  items: UserItem[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function AdminOverviewPage() {
  const [stats, setStats] = useState<SystemStats | null>(null);
  const [users, setUsers] = useState<UserListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [userPage, setUserPage] = useState(1);
  const [userSearch, setUserSearch] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const hasFetchedRef = useRef(false);

  const fetchStats = async () => {
    try {
      const res = await api.get<ApiResponse<SystemStats>>("/admin/stats");
      setStats(res.data.data);
    } catch {
      // Stats fetch failure is non-fatal
    }
  };

  const fetchUsers = async (page: number, search: string) => {
    try {
      const params = new URLSearchParams({ page: String(page), page_size: "10" });
      if (search) params.set("search", search);
      const res = await api.get<ApiResponse<UserListResponse>>(
        `/admin/users?${params.toString()}`,
      );
      setUsers(res.data.data);
    } catch (err) {
      setError(extractApiError(err, "Failed to load users"));
    }
  };

  useEffect(() => {
    if (hasFetchedRef.current) return;
    hasFetchedRef.current = true;
    (async () => {
      setLoading(true);
      await Promise.all([fetchStats(), fetchUsers(1, "")]);
      setLoading(false);
    })();
  }, []);

  const handleSearch = () => {
    setUserSearch(searchInput);
    setUserPage(1);
    fetchUsers(1, searchInput);
  };

  const handlePageChange = (newPage: number) => {
    setUserPage(newPage);
    fetchUsers(newPage, userSearch);
  };

  const handleToggleActive = async (userId: string) => {
    setActionLoading(userId + "-active");
    try {
      await api.put(`/admin/users/${userId}/toggle-active`);
      await fetchUsers(userPage, userSearch);
      await fetchStats();
    } catch (err) {
      setError(extractApiError(err, "Failed to toggle user status"));
    } finally {
      setActionLoading(null);
    }
  };

  const handleToggleAdmin = async (userId: string) => {
    setActionLoading(userId + "-admin");
    try {
      await api.put(`/admin/users/${userId}/toggle-admin`);
      await fetchUsers(userPage, userSearch);
    } catch (err) {
      setError(extractApiError(err, "Failed to toggle admin status"));
    } finally {
      setActionLoading(null);
    }
  };

  if (loading) {
    return <LoadingSpinner text="Loading admin dashboard..." className="py-20" />;
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-foreground">Admin Dashboard</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          System administration and monitoring.
        </p>
      </div>

      {error && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {error}
          <button
            onClick={() => setError("")}
            className="ml-2 underline hover:no-underline"
          >
            dismiss
          </button>
        </div>
      )}

      {/* ---- Stats Cards ---- */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          icon={<Users className="size-5 text-blue-400" />}
          iconBg="bg-blue-500/10"
          label="Total Users"
          value={stats?.users.total ?? 0}
          sublabel={`${stats?.users.active ?? 0} active`}
        />
        <StatCard
          icon={<Sword className="size-5 text-orange-400" />}
          iconBg="bg-orange-500/10"
          label="Challenges"
          value={stats?.challenges.total ?? 0}
          sublabel={`${stats?.challenges.active ?? 0} active`}
        />
        <StatCard
          icon={<Dumbbell className="size-5 text-green-400" />}
          iconBg="bg-green-500/10"
          label="Training Sessions"
          value={stats?.training.total_sessions ?? 0}
          sublabel={`${stats?.training.active_sessions ?? 0} active`}
        />
        <StatCard
          icon={<Trophy className="size-5 text-yellow-400" />}
          iconBg="bg-yellow-500/10"
          label="Contests"
          value={stats?.contests.total ?? 0}
          sublabel={`${stats?.contests.active ?? 0} active`}
        />
      </div>

      {/* ---- Quick Actions ---- */}
      <div className="rounded-xl border border-border bg-card p-5">
        <h2 className="text-sm font-semibold text-foreground">Quick Actions</h2>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <Link
            to="/admin/config"
            className="flex items-center gap-3 rounded-lg border border-border p-3 transition-colors hover:bg-muted"
          >
            <Settings className="size-5 text-muted-foreground" />
            <div>
              <p className="text-sm font-medium text-foreground">Configuration</p>
              <p className="text-xs text-muted-foreground">Manage system settings</p>
            </div>
          </Link>
          <button
            onClick={() => {
              fetchStats();
              fetchUsers(userPage, userSearch);
            }}
            className="flex items-center gap-3 rounded-lg border border-border p-3 text-left transition-colors hover:bg-muted"
          >
            <Activity className="size-5 text-muted-foreground" />
            <div>
              <p className="text-sm font-medium text-foreground">Refresh Data</p>
              <p className="text-xs text-muted-foreground">Reload stats and user list</p>
            </div>
          </button>
        </div>
      </div>

      {/* ---- User Management ---- */}
      <div className="rounded-xl border border-border bg-card p-5">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-2">
            <Users className="size-4 text-muted-foreground" />
            <h2 className="text-sm font-semibold text-foreground">User Management</h2>
          </div>
          <div className="flex gap-2">
            <input
              type="text"
              placeholder="Search users..."
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSearch()}
              className="w-48 rounded-lg border border-input bg-background px-3 py-1.5 text-sm text-foreground placeholder:text-muted-foreground focus:border-primary focus:outline-none"
            />
            <Button variant="outline" size="sm" onClick={handleSearch}>
              <Search className="mr-1 size-3.5" />
              Search
            </Button>
          </div>
        </div>

        {/* User Table */}
        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs text-muted-foreground">
                <th className="pb-2 pr-4">User</th>
                <th className="pb-2 pr-4">Elo</th>
                <th className="pb-2 pr-4">Tokens</th>
                <th className="pb-2 pr-4">Status</th>
                <th className="pb-2 pr-4">Role</th>
                <th className="pb-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {users?.items.map((user) => (
                <tr key={user.id} className="border-b border-border/50 last:border-0">
                  <td className="py-3 pr-4">
                    <div>
                      <p className="font-medium text-foreground">{user.username}</p>
                      <p className="text-xs text-muted-foreground">{user.email}</p>
                    </div>
                  </td>
                  <td className="py-3 pr-4 text-foreground">{user.elo}</td>
                  <td className="py-3 pr-4 text-foreground">{user.tokens}</td>
                  <td className="py-3 pr-4">
                    <span
                      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${
                        user.is_active
                          ? "bg-green-500/10 text-green-400"
                          : "bg-red-500/10 text-red-400"
                      }`}
                    >
                      {user.is_active ? (
                        <UserCheck className="size-3" />
                      ) : (
                        <UserX className="size-3" />
                      )}
                      {user.is_active ? "Active" : "Disabled"}
                    </span>
                  </td>
                  <td className="py-3 pr-4">
                    {user.is_admin ? (
                      <span className="inline-flex items-center gap-1 rounded-full bg-purple-500/10 px-2 py-0.5 text-xs font-medium text-purple-400">
                        <Shield className="size-3" />
                        Admin
                      </span>
                    ) : (
                      <span className="text-xs text-muted-foreground">User</span>
                    )}
                  </td>
                  <td className="py-3">
                    <div className="flex gap-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleToggleActive(user.id)}
                        disabled={actionLoading === user.id + "-active"}
                        title={user.is_active ? "Disable user" : "Enable user"}
                        className="h-7 px-2"
                      >
                        {user.is_active ? (
                          <UserX className="size-3.5 text-red-400" />
                        ) : (
                          <UserCheck className="size-3.5 text-green-400" />
                        )}
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleToggleAdmin(user.id)}
                        disabled={actionLoading === user.id + "-admin"}
                        title={user.is_admin ? "Revoke admin" : "Grant admin"}
                        className="h-7 px-2"
                      >
                        {user.is_admin ? (
                          <ShieldOff className="size-3.5 text-orange-400" />
                        ) : (
                          <Shield className="size-3.5 text-purple-400" />
                        )}
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
              {users && users.items.length === 0 && (
                <tr>
                  <td colSpan={6} className="py-8 text-center text-muted-foreground">
                    No users found
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {users && users.total_pages > 1 && (
          <div className="mt-4 flex items-center justify-between">
            <p className="text-xs text-muted-foreground">
              {users.total} total users
            </p>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => handlePageChange(userPage - 1)}
                disabled={userPage <= 1}
                className="h-7 w-7 p-0"
              >
                <ChevronLeft className="size-4" />
              </Button>
              <span className="text-xs text-muted-foreground">
                Page {userPage} of {users.total_pages}
              </span>
              <Button
                variant="outline"
                size="sm"
                onClick={() => handlePageChange(userPage + 1)}
                disabled={userPage >= users.total_pages}
                className="h-7 w-7 p-0"
              >
                <ChevronRight className="size-4" />
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// StatCard sub-component
// ---------------------------------------------------------------------------

function StatCard({
  icon,
  iconBg,
  label,
  value,
  sublabel,
}: {
  icon: React.ReactNode;
  iconBg: string;
  label: string;
  value: number;
  sublabel?: string;
}) {
  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <div className="flex items-center gap-3">
        <div className={`flex size-10 items-center justify-center rounded-lg ${iconBg}`}>
          {icon}
        </div>
        <div>
          <p className="text-xs text-muted-foreground">{label}</p>
          <p className="text-lg font-semibold text-foreground">{value.toLocaleString()}</p>
          {sublabel && <p className="text-xs text-muted-foreground">{sublabel}</p>}
        </div>
      </div>
    </div>
  );
}
