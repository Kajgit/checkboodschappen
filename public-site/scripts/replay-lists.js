/** Read-only offline replay. Source data and personal-list results stay outside public assets. */
import {loadPyodide} from 'pyodide';
import {initializeMatcher} from '../src/python-matcher.js';
import {normalizeCatalogue} from '../src/checkjebon.js';
import {parseList} from '../src/list-input.js';
import {summarize} from '../src/comparison.js';
import {fileURLToPath} from 'node:url';
import {readFile,writeFile,stat,mkdir} from 'node:fs/promises';
const [cataloguePath,...listPaths]=process.argv.slice(2);
if(!cataloguePath||!listPaths.length)throw new Error('Usage: node scripts/replay-lists.js catalogue.json list.txt [list.txt]');
const memory=[];
const sampleMemory=(phase,py)=>memory.push({phase,...process.memoryUsage(),wasmHeapBytes:py?._module?.HEAP8?.buffer.byteLength??null});
sampleMemory('before-catalogue');
const start=performance.now(),snapshotTime=(await stat(cataloguePath)).mtimeMs;
const catalogue=normalizeCatalogue(JSON.parse(await readFile(cataloguePath,'utf8')),{now:snapshotTime});
sampleMemory('catalogue-normalized');
const py=await loadPyodide({indexURL:fileURLToPath(new URL('../node_modules/pyodide/',import.meta.url))});
const matcher=await initializeMatcher(py,JSON.parse(await readFile('generated/matcher-python.json','utf8')));
sampleMemory('runtime-initialized',py);
const loaded=matcher.load(catalogue.products),initialized=performance.now();
sampleMemory('catalogue-indexed',py);
console.log(`Indexed ${loaded.products} products / ${loaded.tokens} words in ${Math.round(initialized-start)} ms`);
const runs=[];
for(const path of listPaths){
 const items=parseList(await readFile(path,'utf8'));
 const matched=[],lineTimings=[];const listStart=performance.now();
 for(const [index,item] of items.entries()){
  const begin=performance.now();matched.push(matcher.match(item,[]));lineTimings.push(performance.now()-begin);
  sampleMemory(`list-${runs.length+1}-line-${index+1}`,py);
  if((index+1)%10===0)console.log(`${path}: ${index+1}/${items.length}`);
 }
 const comparison=summarize(items,matched,{now:snapshotTime});
 const missing=items.filter((item,i)=>!matched[i].candidates.some(c=>c.decision.status==='accepted'));
 runs.push({path,count:items.length,covered:items.length-missing.length,missing:missing.map(i=>i.query),
  elapsedMs:performance.now()-listStart,lineTimings,comparison,
  diagnostics:items.map((item,i)=>({item,checked:matched[i].checked,review:matched[i].candidates.filter(c=>c.decision.status!=='accepted').slice(0,20)}))});
 console.log(JSON.stringify({path,covered:items.length-missing.length,total:items.length,missing:missing.map(i=>i.query),elapsedMs:Math.round(performance.now()-listStart)}));
}
const output={scope:'OFFLINE matching replay; historical snapshot, not current-price or live-PrijsProfeet verification',snapshotTime:new Date(snapshotTime).toISOString(),
 memoryScope:'Node process checkpoint samples; RSS includes catalogue, JS and WASM; not peak memory or browser/phone evidence',memory,
 catalogueProducts:loaded.products,rejectedSourceRows:catalogue.rejected,startupAndIndexMs:initialized-start,runs};
await mkdir('../output/diagnostics',{recursive:true});await writeFile('../output/diagnostics/public-list-replay.json',JSON.stringify(output,null,2)+'\n');matcher.destroy();
