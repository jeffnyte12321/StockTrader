import { copyFile, mkdir, rm } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import esbuild from "esbuild";

const scriptsDir = path.dirname(fileURLToPath(import.meta.url));
const frontendDir = path.resolve(scriptsDir, "..");
const srcDir = path.join(frontendDir, "src");
const distDir = path.join(frontendDir, "dist");

await rm(distDir, { recursive: true, force: true });
await mkdir(distDir, { recursive: true });

await esbuild.build({
  entryPoints: {
    app: path.join(srcDir, "main.jsx"),
  },
  outdir: distDir,
  bundle: true,
  format: "esm",
  target: ["es2020"],
  sourcemap: false,
  minify: true,
  logLevel: "info",
  entryNames: "[name]",
  define: {
    "process.env.NODE_ENV": "\"production\"",
  },
});

await copyFile(path.join(frontendDir, "index.html"), path.join(distDir, "index.html"));
