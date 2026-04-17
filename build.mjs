#!/usr/bin/env node
/**
 * build.mjs — esbuild script for exec-server.bundle.mjs
 *
 * Usage: node build.mjs
 * Or via: npm run build
 *
 * ADR Decision 3: pinned esbuild as devDep; bundle is reproducible via this script.
 * The --banner:js inject provides a createRequire shim so that CJS modules (e.g.
 * cross-spawn) that call require() at runtime work correctly inside the ESM bundle.
 */

import * as esbuild from "esbuild";

await esbuild.build({
  entryPoints: ["exec-server.js"],
  bundle: true,
  platform: "node",
  format: "esm",
  target: "node20",
  outfile: "exec-server.bundle.mjs",
  banner: {
    js: "import { createRequire } from 'module'; const require = createRequire(import.meta.url);",
  },
});

console.log("Build complete: exec-server.bundle.mjs");
