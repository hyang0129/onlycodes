#!/usr/bin/env node
/**
 * build.mjs — esbuild script for exec-server.bundle.mjs
 *
 * Usage: node exec_server/build.mjs
 * Or via: npm run build
 *
 * ADR Decision 3: pinned esbuild as devDep; bundle is reproducible via this script.
 * The --banner:js inject provides a createRequire shim so that CJS modules (e.g.
 * cross-spawn) that call require() at runtime work correctly inside the ESM bundle.
 */

import * as esbuild from "esbuild";
import { copyFileSync, mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));

await esbuild.build({
  entryPoints: [join(__dirname, "exec-server.js")],
  bundle: true,
  platform: "node",
  format: "esm",
  target: "node20",
  outfile: join(__dirname, "dist", "exec-server.bundle.mjs"),
  banner: {
    js: "import { createRequire } from 'module'; const require = createRequire(import.meta.url);",
  },
});

const distDir = join(__dirname, "dist");
mkdirSync(distDir, { recursive: true });

// Files staged into the agent's cwd at runtime by exec-server.js — must live
// next to the bundle in dist/ because exec-server.js resolves them via its
// own __dirname.
const _RUNTIME_FILES = [
  "passthrough-config.json",
  "codebox.py",
  "mcp_bridge.py",
  "python_kernel.py",
];
for (const fname of _RUNTIME_FILES) {
  copyFileSync(join(__dirname, fname), join(distDir, fname));
}

console.log("Build complete: exec_server/dist/exec-server.bundle.mjs");
for (const fname of _RUNTIME_FILES) {
  console.log(`Copied: exec_server/dist/${fname}`);
}
