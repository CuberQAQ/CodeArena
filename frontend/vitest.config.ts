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
        lines: 90,
        functions: 87,
        branches: 82,
        statements: 88,
      },
      include: ["src/**/*.{ts,tsx}"],
      exclude: [
        "src/types/**",
        "src/test/**",
        "src/**/*.d.ts",
        "src/main.tsx",
      ],
    },
  },
})
