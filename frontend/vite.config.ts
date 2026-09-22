import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { viteExternalsPlugin } from 'vite-plugin-externals'


/**
 * The following libraries are externalized to avoid bundling them with the plugin.
 * These libraries are expected to be provided by the InvenTree core application.
 */
export const externalLibs : Record<string, string> = {
  react: 'React',
  'react-dom': 'ReactDOM',
  'ReactDom': 'ReactDOM',
  '@mantine/core': 'MantineCore',
  "@mantine/notifications": 'MantineNotifications',
  // This plugin does not use lingui directly, but @inventreedb/ui depends on it.
  // Anything it pulls in must resolve to InvenTree's global, not a second copy
  // bundled into the panel.
  '@lingui/core': 'LinguiCore',
  '@lingui/react': 'LinguiReact',
};

// Just the keys of the externalLibs object
const externalKeys = Object.keys(externalLibs);

/**
 * Vite config to build the frontend plugin as an exported module.
 * This will be distributed in the 'static' directory of the plugin.
 */
export default defineConfig({
  plugins: [
    react({
      jsxRuntime: 'classic',
    }),
    viteExternalsPlugin(externalLibs),
  ],
  esbuild: {
    jsx: 'preserve',
  },
  build: {
    // minify: false,
    target: 'esnext',
    cssCodeSplit: false,
    manifest: true,
    sourcemap: true,
    rollupOptions: {
      preserveEntrySignatures: "exports-only",
      // Every entrypoint referenced by plugin_static_file() in core.py must be
      // listed here, or the panel silently fails to render.
      input: [
        './src/PartPanel.tsx',
        './src/LocationPanel.tsx',
        './src/Dashboard.tsx',
        './src/Settings.tsx',
      ],
      output: [
        // Generate two sets of output files:
        // One without hashes - for backwards compatibility
        {
          dir: '../inventree_explosives/static',
          entryFileNames: '[name].js',
          assetFileNames: 'assets/[name].[ext]',
          globals: externalLibs,
        },
        // And one with hashes for cache busting
        {
          dir: '../inventree_explosives/static',
          entryFileNames: '[name]-[hash].js',
          assetFileNames: 'assets/[name].[ext]',
          globals: externalLibs,
        }
      ],
      external: externalKeys,
    }
  },
  optimizeDeps: {
    exclude: externalKeys,
  }
})
