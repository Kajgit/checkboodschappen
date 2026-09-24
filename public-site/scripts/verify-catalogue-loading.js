/** Real WASM/JS boundary regression; synthetic products, no source network. */
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {loadPyodide} from 'pyodide';
import {initializeMatcher} from '../src/python-matcher.js';
const py=await loadPyodide({indexURL:fileURLToPath(new URL('../node_modules/pyodide/',import.meta.url))});
const matcher=await initializeMatcher(py,JSON.parse(await readFile(new URL('../generated/matcher-python.json',import.meta.url),'utf8')));
try {
 const products=Array.from({length:2001},(_,id)=>({id,name:'kokosmelk'}));
 assert.deepEqual(matcher.load(products),{products:2001,tokens:1});
 assert.equal(py.runPython("__import__('bw_matcher.bridge', fromlist=['_index'])._index['kokosmelk'] == list(range(2001))"),true);
 assert.throws(()=>matcher.load([...products,{}]),/name/);
 assert.equal(py.runPython("len(__import__('bw_matcher.bridge', fromlist=['_catalogue'])._catalogue)"),2001);
 assert.equal(py.runPython("__import__('bw_matcher.bridge', fromlist=['_loading'])._loading is None"),true);
 assert.throws(()=>matcher.load(null),/catalogus/);
 assert.deepEqual(matcher.load([{id:2,name:'tortilla'}]),{products:1,tokens:1});
 assert.equal(py.runPython("__import__('bw_matcher.bridge', fromlist=['_index'])._index == {'tortilla': [0]}"),true);
 assert.deepEqual(matcher.load([]),{products:0,tokens:0});
 console.log('Actual WASM catalogue batches: boundary offsets, failed-import rollback, replacement and empty load pass.');
} finally {matcher.destroy();}
