import {readFile,readdir,writeFile} from 'node:fs/promises';
import {dirname,join,resolve} from 'node:path';
import {createHash} from 'node:crypto';

/** Inventory the actual bundled inputs, not just declared top-level dependencies. */
export async function buildNotices(bundleResults) {
 // Tailwind contributes preflight/theme CSS outside esbuild's JS input graph.
 const roots=new Set([resolve('node_modules/tailwindcss'),resolve('node_modules/@fontsource-variable/public-sans')]);
 for(const result of bundleResults) for(const input of Object.keys(result.metafile.inputs)) {
  if(!input.includes('node_modules/'))continue;
  let directory=dirname(resolve(input));
  while(directory!==dirname(directory)) {
   try {await readFile(join(directory,'package.json'));roots.add(directory);break;}catch{}
   directory=dirname(directory);
  }
 }
 const sections=[],packages=[];
 for(const root of [...roots].sort()) {
  const pkg=JSON.parse(await readFile(join(root,'package.json'),'utf8'));
  const files=(await readdir(root)).filter(name=>/^(licen[sc]e|copying|notice|copyrightnotice)(\.|$)/i.test(name)).sort();
  if(!files.length)throw new Error(`Missing bundled dependency licence: ${pkg.name}`);
  packages.push({name:pkg.name,version:pkg.version,license:pkg.license,files});
  for(const file of files)sections.push(`${pkg.name} ${pkg.version} — ${file}\n\n${await readFile(join(root,file),'utf8')}`);
 }
 // Pako's package LICENSE is MIT, but lib/zlib carries separate Zlib notices.
 // Preserve those source headers for every zlib file actually bundled.
 const inputs=new Set(bundleResults.flatMap(result=>Object.keys(result.metafile.inputs)));
 for(const input of [...inputs].filter(path=>path.includes('/pako/lib/zlib/')).sort()) {
  const source=await readFile(input,'utf8');
  const notice=source.match(/(^\/\/ \(C\)[^\n]*\n(?:\/\/[^\n]*\n)+)/m)?.[1];
  if(!notice?.includes('This software is provided'))throw new Error(`Missing Zlib source notice: ${input}`);
  sections.push(`${input}\n\n${notice}`);
 }
 const pyodide=JSON.parse(await readFile('node_modules/pyodide/package.json','utf8'));
 const runtime=JSON.parse(await readFile('node_modules/pyodide/pyodide-lock.json','utf8')).info;
 if(pyodide.version!=='314.0.7'||runtime.python!=='3.14.2'||runtime.platform!=='emscripten_5_0_3')
  throw new Error('Runtime version changed; review and update pinned runtime notices before building.');
 const runtimeAssets=JSON.parse(await readFile('licenses/runtime-assets.json','utf8'));
 if(runtimeAssets.version!==pyodide.version)throw new Error('Runtime asset inventory version mismatch');
 for(const asset of runtimeAssets.assets) {
  for(const directory of ['node_modules/pyodide','dist/vendor/pyodide']) {
   const bytes=await readFile(join(directory,asset.file));
   if(bytes.length!==asset.bytes||createHash('sha256').update(bytes).digest('hex')!==asset.sha256)
    throw new Error(`Runtime artifact changed; review native notices: ${directory}/${asset.file}`);
  }
 }
 const provenance=JSON.parse(await readFile('licenses/provenance.json','utf8'));
 for(const entry of provenance) {
  const bytes=await readFile(join('licenses',entry.file));
  if(createHash('sha256').update(bytes).digest('hex')!==entry.sha256)throw new Error(`Licence integrity mismatch: ${entry.file}`);
  sections.push(`${entry.file}\nSource: ${entry.url}\n\n${bytes.toString('utf8')}`);
 }
 const header=await readFile('licenses/README.txt','utf8');
 const own=await readFile('../LICENSE','utf8');
 await writeFile('dist/THIRD-PARTY-NOTICES.txt',`${header}\n\nApplication licence\n\n${own}\n\n${sections.join('\n\n------------------------------------------------------------\n\n')}`);
 await writeFile('dist/vendor-inventory.json',JSON.stringify({packages,pyodide:{version:pyodide.version,...runtime},runtimeNotices:provenance,runtimeAssets,nativeComponentAuditComplete:true},null,2)+'\n');
 return packages;
}
