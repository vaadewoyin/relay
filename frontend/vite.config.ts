import { defineConfig, loadEnv } from 'vite'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'RELAY_')
  return {
    base: './',
    server: {
      host: '127.0.0.1',
      port: 5173,
      proxy: {
        '/relay-api': {
          target: env.RELAY_PROXY_TARGET || 'http://127.0.0.1:8000',
          rewrite: (path) => path.replace(/^\/relay-api(?=\/|$)/, ''),
        },
      },
    },
    build: { target: 'esnext' },
  }
})
