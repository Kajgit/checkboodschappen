import test from 'node:test';
import assert from 'node:assert/strict';
import {IDBFactory} from 'fake-indexeddb';
import {ListStore,parseBackup,serializeBackup,validateList} from '../src/list-store.js';
const list=()=>({version:1,postcode:'1234 AB',items:[{id:'one',query:'Kokosmelk',quantity:800,unit:'ml'}]});
test('persists exact quantities across reopen and isolates separate browser profiles',async()=>{
  const browserA=new IDBFactory(),browserB=new IDBFactory();
  const a=new ListStore({indexedDB:browserA}),b=new ListStore({indexedDB:browserB});
  await a.save(list());a.close();
  const reopened=new ListStore({indexedDB:browserA});
  assert.equal((await reopened.load()).items[0].quantity,800);
  assert.deepEqual((await b.load()).items,[]);
  await reopened.clear();assert.deepEqual((await reopened.load()).items,[]);
  reopened.close();b.close();
});
test('backup round-trip validates, strips unknown metadata and preserves entries',()=>{
  const value={...list(),secret:'not exported'};
  assert.deepEqual(parseBackup(serializeBackup(value)),validateList(list()));
  assert.equal(serializeBackup(value).includes('secret'),false);
});
test('invalid import cannot overwrite the existing list',async()=>{
  const store=new ListStore({indexedDB:new IDBFactory()});await store.save(list());
  for(const value of [{...list(),version:2},{...list(),items:[{...list().items[0],quantity:-2}]},
      {...list(),items:[...list().items,...list().items]}, {...list(),postcode:'nonsense'}]) {
    assert.throws(()=>parseBackup(JSON.stringify(value)));
  }
  assert.equal((await store.load()).items.length,1);store.close();
});
test('rejects oversized inputs and unavailable browser storage clearly',async()=>{
  assert.throws(()=>parseBackup(' '.repeat(100001)));
  await assert.rejects(new ListStore({indexedDB:null}).load(),/ondersteunt geen/);
});
