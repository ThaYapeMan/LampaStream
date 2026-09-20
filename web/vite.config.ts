import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test-setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    exclude: ['tests/e2e/**'],
    // WSL2 fork startup exceeds the 60 s pool-worker timeout with the default
    // 'forks' pool; vmForks starts workers in the same process space and avoids
    // the issue without sacrificing isolation.
    pool: 'vmForks',
  },
  plugins: [react()],
  // base defaults to '/' which is correct for the dev server.
  // The build script passes --base=/new/ for the temporary FastAPI mount;
  // remove that flag when the app moves to / permanently.
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: {
    // Output directly into the Python package so it is included after pip install.
    outDir: '../src/lampastream/webui',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/api': 'http://localhost:8420',
      '/ws': {
        target: 'ws://localhost:8420',
        ws: true,
      },
    },
  },
})
