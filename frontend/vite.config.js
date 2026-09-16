import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: {
    host: '127.0.0.1',
    proxy: { '/api': 'http://127.0.0.1:8000' },
    watch: { ignored: ['**/src-tauri/**'] },
  },
  build: { target: 'safari15' },
  test: { environment: 'jsdom', setupFiles: './src/test-setup.js' },
});
