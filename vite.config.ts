import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', 'EMMC_DEV_');
  return {
    plugins: [react()],
    server: { proxy: { '/api': env.EMMC_DEV_API || 'http://127.0.0.1:80' } },
  };
});
