import { resolve } from 'node:path'
import process from 'node:process'

import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// Configuration is read from the repository-root .env, the same file Django
// reads, so the two ports are stated once (BUILD_PLAN §2.3).
const repoRoot = resolve(process.cwd(), '..')

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, repoRoot, '')

  const djangoPort = env.DJANGO_DEV_PORT ?? '8001'
  const vitePort = Number(env.VITE_DEV_PORT ?? '5173')

  return {
    plugins: [react()],

    // In production the bundle is served by WhiteNoise from /static/. In
    // development Vite serves it from the root, because a dev server rooted at
    // /static/ is a paper cut every single time.
    base: mode === 'production' ? '/static/' : '/',

    resolve: {
      alias: { '@': resolve(process.cwd(), 'src') },
    },

    server: {
      port: vitePort,
      // Vite refuses requests whose Host header it does not recognise. The
      // browser check drives the app from inside a container, which reaches
      // the host as `host.docker.internal`, so that name has to be allowed —
      // but only for the check. The everyday dev server keeps Vite's default
      // protection, because relaxing it there would be relaxing it always.
      ...(process.env.VITE_CHECK === '1'
        ? { allowedHosts: ['host.docker.internal', 'localhost', '127.0.0.1'] }
        : {}),
      // Fail rather than silently move to another port: the port is written
      // into CSRF_TRUSTED_ORIGINS, and a silent move produces a login that
      // fails for no visible reason.
      strictPort: true,
      proxy: {
        // The whole point of the dev server. /api is proxied to Django so the
        // browser sees one origin, which keeps the session cookie behaving in
        // development exactly as it will in production — no CORS layer, no
        // django-cors-headers, and no class of bug that only appears after
        // deployment.
        '/api': {
          target: `http://localhost:${djangoPort}`,
          changeOrigin: false,
        },
      },
    },

    build: {
      outDir: 'dist',
      emptyOutDir: true,
      // Vite content-hashes every asset filename, which is why Django's static
      // storage is compressed rather than manifest-hashed.
      sourcemap: false,
    },
  }
})
