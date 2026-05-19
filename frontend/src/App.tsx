import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { useEffect } from "react";

import { useAuthStore } from "@/stores/auth";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { AdminRoute } from "@/components/AdminRoute";
import { AuthLayout } from "@/layouts/AuthLayout";
import { MainLayout } from "@/layouts/MainLayout";
import { AdminLayout } from "@/layouts/AdminLayout";

// Pages
import LoginPage from "@/pages/LoginPage";
import RegisterPage from "@/pages/RegisterPage";
import DashboardPage from "@/pages/DashboardPage";
import ChallengePage from "@/pages/ChallengePage";
import PvEChallengePage from "@/pages/challenge/PvEChallengePage";
import TrainingPage from "@/pages/TrainingPage";
import TrainingDetailPage from "@/pages/TrainingDetailPage";
import ContestPage from "@/pages/ContestPage";
import ContestDetailPage from "@/pages/ContestDetailPage";
import ProfilePage from "@/pages/ProfilePage";
import CFBindPage from "@/pages/CFBindPage";
import LeaderboardPage from "@/pages/LeaderboardPage";
import AdminOverviewPage from "@/pages/AdminOverviewPage";
import AdminConfigPage from "@/pages/AdminConfigPage";

function AuthInitializer({ children }: { children: React.ReactNode }) {
  const hydrate = useAuthStore((s) => s.hydrate);

  useEffect(() => {
    hydrate();
  }, [hydrate]);

  return <>{children}</>;
}

function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <AuthInitializer>
          <Routes>
            {/* ---- Auth routes (no login required) ---- */}
            <Route element={<AuthLayout />}>
              <Route path="/" element={<LoginPage />} />
              <Route path="/register" element={<RegisterPage />} />
            </Route>

            {/* ---- Main app routes (login required) ---- */}
            <Route
              element={
                <ProtectedRoute>
                  <MainLayout />
                </ProtectedRoute>
              }
            >
              <Route path="/dashboard" element={<DashboardPage />} />
              <Route path="/challenge" element={<ChallengePage />} />
              <Route path="/pve-challenge" element={<PvEChallengePage />} />
              <Route path="/training" element={<TrainingPage />} />
              <Route path="/training/:id" element={<TrainingDetailPage />} />
              <Route path="/contest" element={<ContestPage />} />
              <Route path="/contest/:id" element={<ContestDetailPage />} />
              <Route path="/profile" element={<ProfilePage />} />
              <Route path="/profile/cf-bind" element={<CFBindPage />} />
              <Route path="/leaderboard" element={<LeaderboardPage />} />
            </Route>

            {/* ---- Admin routes (login + admin required) ---- */}
            <Route
              element={
                <AdminRoute>
                  <AdminLayout />
                </AdminRoute>
              }
            >
              <Route path="/admin" element={<AdminOverviewPage />} />
              <Route path="/admin/config" element={<AdminConfigPage />} />
            </Route>

            {/* ---- Catch-all ---- */}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </AuthInitializer>
      </BrowserRouter>
    </ErrorBoundary>
  );
}

export default App;
