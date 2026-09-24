import test from 'node:test';
import assert from 'node:assert/strict';
import {Miniflare,convertV4MiniflareOptions} from 'miniflare';
import {build} from 'esbuild';
// Test-only subclass exposes storage evidence through the local namespace.
// It is never part of the production entry point or asset build.
const bundle=await build({stdin:{resolveDir:process.cwd(),contents:`
import worker,{ProviderCoordinator} from './server/worker.js';
export default worker;
export class TestCoordinator extends ProviderCoordinator {
 constructor(ctx,env) {
  super(ctx,env);this.metrics={reads:0,writes:0};
  const sql=this.sql;
  this.sql={exec:(...args)=>{
   const cursor=sql.exec(...args);let reads=cursor.rowsRead,writes=cursor.rowsWritten;
   this.metrics.reads+=reads;this.metrics.writes+=writes;
   return {toArray:()=>{
    const result=cursor.toArray();this.metrics.reads+=cursor.rowsRead-reads;this.metrics.writes+=cursor.rowsWritten-writes;
    reads=cursor.rowsRead;writes=cursor.rowsWritten;return result;
   }};
  }};
 }
 async fetch(request) {
  const path=new URL(request.url).pathname;
  if(path==='/test/seed-cache') {
   for(let i=0;i<200;i++)this.sql.exec('INSERT OR REPLACE INTO app_cache VALUES(?,?,?)','seed-'+i,Date.now()+60000+i,JSON.stringify({products:[],complete:true}));
  } else if(path==='/test/yesterday-exhausted') {
   const yesterday=Math.floor(Date.now()/86400000)-1;
   this.sql.exec('INSERT OR REPLACE INTO traffic_budget VALUES(1,?,6000)',yesterday);
   this.sql.exec('UPDATE visitor_budget SET day=?,daily=200,window=?,count=120',yesterday,Math.floor(Date.now()/3600000)-24);
   this.sql.exec('UPDATE app_cache SET expires=?',Date.now()-1);
   await this.ctx.storage.put('upstream-budget',{requests:[],day:yesterday,daily:5000,cooldown:0});
  } else if(path==='/test/exhaust') {
   this.sql.exec('INSERT OR REPLACE INTO traffic_budget VALUES(1,?,6000)',Math.floor(Date.now()/86400000));
  } else if(path==='/test/expire') {
   this.sql.exec('UPDATE app_cache SET expires=?',Date.now()-1);
   this.sql.exec('UPDATE visitor_budget SET day=?',Math.floor(Date.now()/86400000)-1);
   await this.alarm();
  } else if(path!=='/test/inspect') return super.fetch(request);
  return Response.json({traffic:this.sql.exec('SELECT * FROM traffic_budget').toArray(),upstream:await this.ctx.storage.get('upstream-budget'),cache:this.sql.exec('SELECT * FROM app_cache').toArray(),
   visitors:this.sql.exec('SELECT * FROM visitor_budget').toArray(),alarm:await this.ctx.storage.getAlarm(),metrics:this.metrics});
 }
}`},bundle:true,format:'esm',write:false,platform:'browser'});
const source=bundle.outputFiles[0].text;
function runtime({bindings={},upstream}={}) {
  return new Miniflare(convertV4MiniflareOptions({modules:true,script:source,compatibilityDate:'2026-09-01',
    durableObjects:{COORDINATOR:{className:'TestCoordinator',useSQLite:true}},
    bindings:{PRIJSPROFEET_ENABLED:'true',VISITOR_HASH_SECRET:'synthetic-secret',PUBLIC_APP_URL:'https://app.test',...bindings},
    outboundService:upstream||(()=>{throw new Error('Unexpected network access');})}));
}
const request=(mf,query='kokosmelk',headers={})=>mf.dispatchFetch('https://app.test/api/search',{
  method:'POST',headers:{Origin:'https://app.test','Content-Type':'application/json','CF-Connecting-IP':'192.0.2.1',...headers},
  body:JSON.stringify({query})});
const payload=()=>({page:1,page_size:100,total:1,results:[{product_id:'synthetic',name:'Test kokosmelk',retailer:'jumbo',price:2,
  quantity:'400 ml',promotion_status:'shelf',extracted_at:new Date().toISOString()}]});
test('real Worker and SQLite coordinator cache normalized results across visitors',async()=>{
  let calls=0;const mf=runtime({upstream:async()=>{calls++;return Response.json(payload());}});
  try {
    const first=await request(mf);assert.equal(first.status,200,await first.clone().text());
    const a=await first.json();assert.equal(a.products[0].priceCents,200);assert.equal(a.cacheHit,false);
    const second=await request(mf,'kokosmelk',{'CF-Connecting-IP':'192.0.2.2'});
    assert.equal((await second.json()).cacheHit,true);assert.equal(calls,1);
    assert.equal(second.headers.get('cache-control'),'no-store');
  } finally {await mf.dispose();}
});
test('distinct visitors share the same upstream request budget',async()=>{
  let calls=0;const mf=runtime({bindings:{SOURCE_MINUTE_LIMIT:'1'},upstream:async()=>{calls++;return Response.json(payload());}});
  try {
    assert.equal((await request(mf)).status,200);
    const second=await request(mf,'rijst',{'CF-Connecting-IP':'192.0.2.2'});
    assert.equal(second.status,429);assert.equal((await second.json()).error,'provider_busy');assert.equal(calls,1);
  } finally {await mf.dispose();}
});
test('untrusted origins, oversized bodies and disabled sources never reach upstream',async()=>{
  const mf=runtime();
  try {
    assert.equal((await request(mf,'kokosmelk',{Origin:'https://evil.test'})).status,403);
    const big=await mf.dispatchFetch('https://app.test/api/search',{method:'POST',headers:{Origin:'https://app.test','Content-Type':'application/json'},body:' '.repeat(3000)});
    assert.equal(big.status,413);
    assert.equal((await request(mf,'*')).status,400);
  } finally {await mf.dispose();}
  const disabled=runtime({bindings:{PRIJSPROFEET_ENABLED:'false'}});
  try {assert.equal((await request(disabled)).status,503);}finally{await disabled.dispose();}
});
test('cached requests still consume visitor allowance without exhausting another visitor',async()=>{
  let calls=0;const mf=runtime({upstream:async()=>{calls++;return Response.json(payload());}});
  try {
    for(let i=0;i<120;i++) assert.equal((await request(mf)).status,200);
    const limited=await request(mf);assert.equal(limited.status,429);
    assert.equal((await limited.json()).error,'visitor_budget_exhausted');
    assert.equal((await request(mf,'kokosmelk',{'CF-Connecting-IP':'192.0.2.9'})).status,200);
    assert.equal(calls,1);
  } finally {await mf.dispose();}
});

async function inspect(mf,path='inspect') {
  const ns=await mf.getDurableObjectNamespace('COORDINATOR');
  return (await ns.get(ns.idFromName('global-provider-v1')).fetch(`https://test.internal/test/${path}`)).json();
}
test('failed searches still schedule visitor deletion with no cached products',async()=>{
  const mf=runtime({upstream:()=>new Response('',{status:403})});
  try {
    assert.equal((await request(mf)).status,503);
    const stored=await inspect(mf);
    assert.equal(stored.cache.length,0);assert.equal(stored.visitors.length,1);
    assert.ok(stored.alarm>Date.now());assert.ok(stored.alarm<=Date.now()+86400000);
    assert.match(stored.visitors[0].id,/^[a-f0-9]{64}$/);
    const expired=await inspect(mf,'expire');
    assert.deepEqual(expired.visitors,[]);assert.deepEqual(expired.cache,[]);assert.equal(expired.alarm,null);
  } finally {await mf.dispose();}
});
test('expiry physically deletes cached source data and visitor rows',async()=>{
  let calls=0;const mf=runtime({upstream:()=>{calls++;return Response.json(payload());}});
  try {
    assert.equal((await request(mf)).status,200);
    const before=await inspect(mf);assert.equal(before.cache.length,1);assert.equal(before.visitors.length,1);
    assert.ok(before.alarm<=Date.now()+300000);
    const after=await inspect(mf,'expire');
    assert.deepEqual(after.cache,[]);assert.deepEqual(after.visitors,[]);assert.equal(after.alarm,null);
    assert.equal((await request(mf)).status,200);assert.equal(calls,2);
  } finally {await mf.dispose();}
});

test('shared warm-cache traffic has bounded SQLite reads as visitor count grows',async()=>{
  let calls=0;const mf=runtime({upstream:()=>{calls++;return Response.json(payload());}});
  try {
    const start=performance.now();
    for(let i=0;i<300;i++) {
      const ip=`192.0.${Math.floor(i/250)}.${i%250+1}`;
      assert.equal((await request(mf,'kokosmelk',{'CF-Connecting-IP':ip})).status,200);
    }
    const evidence=await inspect(mf);
    assert.equal(calls,1);assert.equal(evidence.visitors.length,300);
    assert.ok(evidence.metrics.reads<10000,JSON.stringify(evidence.metrics));
    console.log(JSON.stringify({scope:'Local synthetic runtime; explicit SQL only, excludes KV/alarm metering and cloud CPU',requests:300,upstreamCalls:calls,
      milliseconds:Math.round(performance.now()-start),sql:evidence.metrics}));
  } finally {await mf.dispose();}
});

test('application daily ceiling returns a reset time without fetching upstream',async()=>{
  const mf=runtime();
  try {
    await inspect(mf,'exhaust');
    const response=await request(mf);
    assert.equal(response.status,429);assert.equal((await response.json()).error,'daily_budget_exhausted');
    const expected=Math.ceil((86400000-Date.now()%86400000)/1000);
    assert.ok(Math.abs(Number(response.headers.get('retry-after'))-expected)<=1);
  } finally {await mf.dispose();}
});

 test('mixed cold and warm searches keep a full cache bounded and delete it on expiry',async()=>{
  let calls=0;const mf=runtime({upstream:()=>{calls++;return Response.json(payload());}});
  try {
   await inspect(mf,'seed-cache');
   const start=performance.now();
   for(let i=0;i<80;i++){
    const query=`kokosmelk ${i}`;
    const first=await request(mf,query,{'CF-Connecting-IP':`192.0.2.${i+1}`});
    assert.equal(first.status,200);assert.equal((await first.json()).cacheHit,false);
    const warm=await request(mf,query,{'CF-Connecting-IP':`198.51.100.${i+1}`});
    assert.equal(warm.status,200);assert.equal((await warm.json()).cacheHit,true);
   }
   const state=await inspect(mf);
   assert.equal(calls,80);assert.equal(state.cache.length,200);assert.equal(state.visitors.length,160);
   assert.equal(state.cache.filter(row=>row.key.startsWith('seed-')).length,120);
   assert.ok(state.metrics.reads<100000,JSON.stringify(state.metrics));
   console.log(JSON.stringify({scope:'Local synthetic mixed load; preseeded cache; explicit SQL excludes KV/alarms and cloud CPU',requests:160,upstreamCalls:calls,cacheRows:state.cache.length,milliseconds:Math.round(performance.now()-start),sql:state.metrics}));
   const expired=await inspect(mf,'expire');
   assert.deepEqual(expired.cache,[]);assert.deepEqual(expired.visitors,[]);assert.equal(expired.alarm,null);
  } finally {await mf.dispose();}
 });

test('first request after an exhausted prior day resets all budgets and removes old data',async()=>{
 let calls=0;const mf=runtime({upstream:()=>{calls++;return Response.json(payload());}});
 try {
  assert.equal((await request(mf)).status,200);
  const before=await inspect(mf,'yesterday-exhausted');
  assert.equal(before.traffic[0].count,6000);assert.equal(before.upstream.daily,5000);
  assert.equal(before.visitors[0].daily,200);
  const response=await request(mf);assert.equal(response.status,200);
  assert.equal((await response.json()).cacheHit,false);assert.equal(calls,2);
  const after=await inspect(mf),day=Math.floor(Date.now()/86400000);
  assert.equal(after.traffic[0].day,day);assert.equal(after.traffic[0].count,1);
  assert.equal(after.upstream.day,day);assert.equal(after.upstream.daily,1);
  assert.equal(after.visitors.length,1);assert.equal(after.visitors[0].day,day);
  assert.equal(after.visitors[0].daily,1);assert.equal(after.visitors[0].count,1);
  assert.equal(after.cache.length,1);assert.ok(after.cache[0].expires>Date.now());
 } finally {await mf.dispose();}
});

test('large paginated responses preserve all products and charge every page without oversized cache entries',async()=>{
 let calls=0;
 const mf=runtime({bindings:{SOURCE_MINUTE_LIMIT:'46'},upstream:request=>{
  calls++;const url=new URL(request.url);
  if(url.searchParams.get('q')==='small')return Response.json(payload());
  const page=Number(url.searchParams.get('page'));
  return Response.json({page,page_size:100,total:400,results:Array.from({length:100},(_,i)=>({...payload().results[0],product_id:`synthetic-${page}-${i}`}))});
 }});
 try{
  const start=performance.now();
  const small=await request(mf,'small');assert.equal((await small.json()).products.length,1);
  for(let i=0;i<11;i++){
   const response=await request(mf,'large',{'CF-Connecting-IP':`192.0.2.${i+2}`});
   assert.equal(response.status,200);const result=await response.json();
   assert.equal(result.products.length,400);assert.equal(result.complete,true);assert.equal(result.cacheHit,false);
   assert.equal(new Set(result.products.map(p=>p.productId)).size,400);
  }
  assert.equal(calls,45);
  const limited=await request(mf,'large',{'CF-Connecting-IP':'192.0.2.50'});
  assert.equal(limited.status,200);const partial=await limited.json();
  assert.equal(partial.complete,false);assert.equal(partial.products.length,100);assert.equal(partial.reason,'provider_busy');
  assert.equal(calls,46);
  const warm=await request(mf,'small',{'CF-Connecting-IP':'192.0.2.51'});
  assert.equal((await warm.json()).cacheHit,true);assert.equal(calls,46);
  const state=await inspect(mf);assert.equal(state.cache.length,1);assert.equal(state.upstream.daily,46);
  console.log(JSON.stringify({scope:'Local four-page synthetic responses exceed cache-size ceiling; includes incomplete final query and warm-cache recovery; excludes cloud CPU/KV/alarms',requests:14,upstreamCalls:calls,completeProductsPerLargeQuery:400,cacheRows:state.cache.length,milliseconds:Math.round(performance.now()-start),sql:state.metrics}));
 }finally{await mf.dispose();}
});
