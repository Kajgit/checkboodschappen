/** Initialize a private Python package from locally served application code. */
export async function initializeMatcher(pyodide, modules) {
  const root='/home/pyodide/bw_matcher';
  pyodide.FS.mkdirTree(root);
  for(const [name,source] of Object.entries(modules)) {
    if(!/^(?:__init__|groceries|product_text|product_identity|product_facts|bridge)$/.test(name)) throw new Error('Unexpected matcher module');
    pyodide.FS.writeFile(`${root}/${name}.py`,source,{encoding:'utf8'});
  }
  await pyodide.runPythonAsync('from bw_matcher.bridge import evaluate_json, catalogue_batch_json, match_item_json');
  const evaluate=pyodide.globals.get('evaluate_json');
  const load=pyodide.globals.get('catalogue_batch_json'),match=pyodide.globals.get('match_item_json');
  return {load(products) {
      if(!Array.isArray(products)||products.length>150000)throw new Error('Ongeldige catalogus');
      load('begin');
      try {
        for(let offset=0;offset<products.length;offset+=2000)load('append',JSON.stringify(products.slice(offset,offset+2000)));
        return JSON.parse(load('commit'));
      } catch(error) {load('abort');throw error;}
    },
    match(item,extra=[]) {return JSON.parse(match(JSON.stringify({item,extra})));},evaluate(entries) {return JSON.parse(evaluate(JSON.stringify(entries)));},destroy(){evaluate.destroy();load.destroy();match.destroy();}};
}
