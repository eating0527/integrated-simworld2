import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    globals: true,
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    allowedHosts: true,
    proxy: {
      // REST API
      '/api': {
        target: 'http://localhost:8888',
        changeOrigin: true,
      },
      // 靜態上傳照片
      '/uploads': {
        target: 'http://localhost:8888',
        changeOrigin: true,
      },
      // 動態生成場景（GLB）
      '/generated-scenes': {
        target: 'http://localhost:8888',
        changeOrigin: true,
      },
      // Simulation result images
      '/simulations': {
        target: 'http://localhost:8888',
        changeOrigin: true,
      },
      // WebSocket
      '/ws': {
        target: 'ws://localhost:8888',
        ws: true,
        changeOrigin: true,
      },
    },
  },
});
