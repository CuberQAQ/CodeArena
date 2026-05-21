import path from "path"
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: true,
    pool: "forks",
    fileParallelism: false,
    exclude: ["node_modules", "e2e", "e2e/**"],
    coverage: {
      provider: "istanbul",
      reporter: ["text", "json", "html"],
      thresholds: {
        lines: 80,
        functions: 80,
        branches: 80,
        statements: 80,
      },
      include: ["src/**/*.{ts,tsx}"],
      exclude: [
        "src/types/**",
        "src/test/**",
        "src/**/*.d.ts",
        "src/main.tsx",
        "src/i18n.ts",
        "src/App.tsx",
        "src/components/ErrorBoundary.tsx",
        "src/components/LanguageSwitcher.tsx",
        "src/components/LoadingSpinner.tsx",
        "src/components/ui/button.tsx",
        "src/components/animations/index.ts",
        "src/components/medal/index.ts",
        "src/layouts/AuthLayout.tsx",
        "src/lib/utils.ts",
        "src/pages/TrainingDetailPage.tsx",
        "src/components/charts/EloChart.tsx",
        "src/components/charts/PPChart.tsx",
        "src/components/charts/RadarChart.tsx",
        "src/components/charts/StatsPanel.tsx",
      ],
    },
  },
})
