import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'

// Per-project frontend folders live at the repo root (../../<project>/frontend)
const repoRoot = path.resolve(__dirname, '../..')

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@app':         path.resolve(__dirname, 'src'),
      '@backtesting': path.join(repoRoot, 'backtesting/frontend'),
      '@stress':      path.join(repoRoot, 'stress_testing/frontend'),
      '@forward':     path.join(repoRoot, 'forward_testing/frontend'),
      '@paper':       path.join(repoRoot, 'paper_trading/frontend'),
      '@reelbt':      path.join(repoRoot, 'reel_to_backtest/frontend'),
      '@reelpipe':    path.join(repoRoot, 'reel_to_pipeline/frontend'),
    },
  },
  server: {
    port: 3000,
    fs: {
      // allow serving project frontend files that live outside the Vite root
      allow: [repoRoot],
    },
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        timeout:      0,        // no socket timeout — SSE streams stay open
        proxyTimeout: 0,        // no outgoing timeout — data fetch can take time
      },
    },
  },
})
