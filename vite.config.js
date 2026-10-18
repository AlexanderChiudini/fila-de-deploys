import { defineConfig } from 'vite';
import { copyFileSync, cpSync } from 'node:fs';
import vue from '@vitejs/plugin-vue';

export default defineConfig({
    publicDir: false,
    plugins: [vue(), {
        name: 'queue-manifest',
        closeBundle() {
            copyFileSync('public/build/.vite/manifest.json', 'resources/views/assets.json');
            cpSync('public/build/assets', 'resources/views/build/assets', { recursive: true });
        },
    }],
    build: {
        outDir: 'public/build',
        manifest: true,
        rollupOptions: { input: 'resources/js/app.js' },
    },
    base: '/build/',
});
