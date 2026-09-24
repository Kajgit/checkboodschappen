import {loadPyodide} from '../vendor/pyodide/pyodide.mjs';
import {initializeMatcher} from './python-matcher.js';
import {summarize} from './comparison.js';
import {validateStores,applyLocations} from './locations.js';
import {addStoreCombinations} from './store-combinations.js';
const ready=(async()=>{
  const start=performance.now();
  const [py,response]=await Promise.all([
    loadPyodide({indexURL:new URL('../vendor/pyodide/',import.meta.url).href}),
    fetch(new URL('../generated/matcher-python.json',import.meta.url))]);
  if(!response.ok) throw new Error('De lokale vergelijker kon niet worden geladen.');
  const matcher=await initializeMatcher(py,await response.json());
  return {matcher,startupMs:performance.now()-start};
})();
// Only structured matching requests are accepted, never executable user-supplied Python.
self.onmessage=async({data})=>{
  const id=data?.id;
  try {
    if(!['evaluate','load','match','finalize'].includes(data?.action||'evaluate')) throw new Error('Ongeldige vergelijkingsopdracht.');
    const {matcher,startupMs}=await ready;
    const start=performance.now();
    let results;
    if(data.action==='finalize') {
      if(!Array.isArray(data.items)||data.items.length>200||!Array.isArray(data.matched)||data.matched.length!==data.items.length)throw new Error('Ongeldige mandjesopdracht.');
      const comparison=summarize(data.items,data.matched,data.options);
      results=addStoreCombinations(applyLocations(comparison,data.origin,validateStores(data.stores),data.locationOptions));
      // Candidate alternatives are needed only while allocating, not in the UI.
      results.baskets=results.baskets.map(({choiceRows,...basket})=>basket);
    } else if(data.action==='load') {
      if(!Array.isArray(data.products)||data.products.length>150000) throw new Error('Ongeldige catalogus.');
      results=matcher.load(data.products);
    } else if(data.action==='match') {
      if(!data.item||typeof data.item.query!=='string'||!Array.isArray(data.extra)||data.extra.length>1000) throw new Error('Ongeldige productregel.');
      results=matcher.match(data.item,data.extra);
    } else {
      if(!Array.isArray(data.entries)||data.entries.length>10000) throw new Error('Ongeldige vergelijkingsopdracht.');
      results=matcher.evaluate(data.entries);
    }
    self.postMessage({id,results,startupMs,durationMs:performance.now()-start});
  } catch(error) {self.postMessage({id,error:error.message});}
};
