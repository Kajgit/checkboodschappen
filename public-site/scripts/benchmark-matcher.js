import {fileURLToPath} from 'node:url';
import {loadPyodide} from 'pyodide';
import {initializeMatcher} from '../src/python-matcher.js';
import {cases} from '../tests/matcher-cases.js';
import {readFile,stat,mkdir,writeFile} from 'node:fs/promises';
import {spawnSync} from 'node:child_process';
import {gzipSync} from 'node:zlib';
import assert from 'node:assert/strict';
const start=performance.now();
const py=await loadPyodide({indexURL:fileURLToPath(new URL('../node_modules/pyodide/',import.meta.url))});
const modules=JSON.parse(await readFile(new URL('../generated/matcher-python.json',import.meta.url),'utf8'));
const matcher=await initializeMatcher(py,modules);
const initialized=performance.now();
const result=matcher.evaluate(cases);
for(let i=0;i<cases.length;i++) assert.equal(result[i].status,cases[i].expected,`${cases[i].item.query} -> ${cases[i].product.name}`);
const reference=spawnSync('../.venv/bin/python',['-c',`
import json,sys,types
modules=json.load(open('generated/matcher-python.json'))
pkg=types.ModuleType('bw_matcher');pkg.__path__=[];sys.modules['bw_matcher']=pkg
for name in ['product_text','product_identity','product_facts','groceries','bridge']:
 mod=types.ModuleType('bw_matcher.'+name);mod.__package__='bw_matcher';sys.modules[mod.__name__]=mod
 exec(compile(modules[name],name,'exec'),mod.__dict__)
print(sys.modules['bw_matcher.bridge'].evaluate_json(sys.stdin.read()))
`],{input:JSON.stringify(cases),encoding:'utf8'});
assert.equal(reference.status,0,reference.stderr);assert.deepEqual(result,JSON.parse(reference.stdout));
const batch=Array.from({length:100},()=>cases).flat();
const before=performance.now();matcher.evaluate(batch);const elapsed=performance.now()-before;
const sizes=[];
for(const file of ['pyodide.mjs','pyodide.asm.mjs','pyodide.asm.wasm','python_stdlib.zip','pyodide-lock.json']) {
 try {const data=await readFile(new URL(`../node_modules/pyodide/${file}`,import.meta.url));sizes.push({file,bytes:data.length,gzipBytes:gzipSync(data).length});}catch{}
}
const evidence={runtime:'Node WebAssembly; not yet a browser/slow-device benchmark',startupMs:initialized-start,
 cases:cases.length,pythonParity:true,decisions:batch.length,batchMs:elapsed,assets:sizes,checkedAt:new Date().toISOString()};
await mkdir('../output/diagnostics',{recursive:true});
await writeFile('../output/diagnostics/browser-matcher-spike.json',JSON.stringify(evidence,null,2)+'\n');
console.log(JSON.stringify(evidence,null,2));matcher.destroy();
