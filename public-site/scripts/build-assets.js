import { build } from "esbuild";
import { execFileSync } from "node:child_process";
import { mkdir, cp, rm, readFile } from "node:fs/promises";
import { buildNotices } from "./build-notices.js";
import { validateStores } from "../src/locations.js";
// A public build must not silently omit the licensed location database.
const locationData = validateStores(
  JSON.parse(await readFile("generated/stores.json", "utf8")),
);
if (
  locationData.license !== "ODbL-1.0" ||
  !Array.isArray(locationData.stores) ||
  locationData.stores.length < 1000
)
  throw new Error(
    "Build a validated national location snapshot first; see README.md.",
  );
if (locationData.stale)
  console.warn(
    "Location snapshot is older than 30 days; refresh before publication.",
  );
await rm("dist", { recursive: true, force: true });
await mkdir("dist/vendor/pyodide", { recursive: true });
await cp("ui", "dist", { recursive: true });
await cp("src", "dist/src", { recursive: true });
await cp("generated", "dist/generated", { recursive: true });
await mkdir("dist/fonts", { recursive: true });
for (const subset of ["latin", "latin-ext"]) {
  const name = `public-sans-${subset}-wght-normal.woff2`;
  await cp(
    `node_modules/@fontsource-variable/public-sans/files/${name}`,
    `dist/fonts/${name}`,
  );
}
for (const file of [
  "pyodide.mjs",
  "pyodide.asm.mjs",
  "pyodide.asm.wasm",
  "python_stdlib.zip",
  "pyodide-lock.json",
]) {
  await cp(`node_modules/pyodide/${file}`, `dist/vendor/pyodide/${file}`);
}
execFileSync(
  process.execPath,
  [
    "node_modules/@tailwindcss/cli/dist/index.mjs",
    "-i",
    "ui/style.css",
    "-o",
    "dist/style.css",
    "--minify",
  ],
  { stdio: "inherit" },
);
const bundles = await Promise.all([
  build({
    entryPoints: ["src/app.jsx"],
    bundle: true,
    format: "esm",
    outfile: "dist/src/app.js",
    minify: true,
    metafile: true,
    jsx: "automatic",
    external: ["./receipt.js"],
  }),
  build({
    entryPoints: ["node_modules/pdf-lib/es/index.js"],
    bundle: true,
    format: "esm",
    outfile: "dist/vendor/pdf-lib.js",
    minify: true,
    metafile: true,
  }),
  build({
    entryPoints: ["node_modules/fflate/esm/browser.js"],
    bundle: true,
    format: "esm",
    outfile: "dist/vendor/fflate.js",
    minify: true,
    metafile: true,
  }),
]);
const packages = await buildNotices(bundles);
console.log(
  `Built self-hosted assets and notices for ${packages.length} bundled JS packages plus pinned runtime notices. No deployment performed.`,
);
