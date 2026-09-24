import test from 'node:test';
import assert from 'node:assert/strict';
import {ProviderService,searchQuery,retryDelay} from '../server/provider-service.js';
const now=Date.parse('2026-09-24T12:00:00Z');
class Storage {
  data=new Map();
  async get(k) {return structuredClone(this.data.get(k));}
  async put(k,v) {this.data.set(k,structuredClone(v));}
}
const raw={product_id:'test',name:'Test kokosmelk',retailer:'jumbo',price:2,quantity:'400 ml',promotion_status:'shelf',extracted_at:new Date(now).toISOString()};
const response=(page=1,total=1,results=[raw])=>Response.json({page,total,page_size:100,results});
const create=options=>new ProviderService({storage:new Storage(),clock:()=>now,fetcher:async()=>response(),...options});
test('rejects wildcard/bulk-like malformed queries and canonicalizes normal input',()=>{
  for(const query of ['*','a','?',{},'kokos\u0000melk']) assert.throws(()=>searchQuery(query));
  assert.equal(searchQuery('  Kokosmelk  light '),'kokosmelk light');
});
test('uses canonical endpoint and private key without exposing key in output',async()=>{
  const service=create({key:'secret',fetcher:async(url,init)=>{
    assert.equal(url.pathname,'/api/v1/search');assert.equal(url.searchParams.get('q'),'kokosmelk');
    assert.equal(init.headers['X-API-Key'],'secret');return response();
  }});
  const result=await service.search('Kokosmelk');assert.equal(result.complete,true);
  assert.equal(result.products[0].priceCents,200);assert.equal(JSON.stringify(result).includes('secret'),false);
});
test('coalesces simultaneous searches and bounds independent concurrency',async()=>{
  let release,calls=0;const wait=new Promise(resolve=>{release=resolve;});
  const service=create({concurrency:1,fetcher:async()=>{calls++;await wait;return response();}});
  const first=service.search('kokosmelk'),second=service.search('Kokosmelk');
  await assert.rejects(service.search('rijst'),e=>e.code==='provider_busy');
  release();assert.deepEqual(await first,await second);assert.equal(calls,1);
});
test('persistent sliding minute budget survives coordinator recreation',async()=>{
  const storage=new Storage();let calls=0;
  const options={storage,minuteLimit:1,fetcher:async()=>{calls++;return response();}};
  await create(options).search('kokosmelk');
  await assert.rejects(create(options).search('rijst'),e=>e.code==='provider_busy'&&e.retryAfter===60);
  assert.equal(calls,1);
});
test('daily budget is distinct from minute budget',async()=>{
  const service=create({dayLimit:1});await service.search('kokosmelk');
  await assert.rejects(service.search('rijst'),e=>e.code==='daily_budget_exhausted');
});
test('429 cooldown persists and prevents immediate retries across queries',async()=>{
  const storage=new Storage();let calls=0;
  const options={storage,fetcher:async()=>{calls++;return new Response('',{status:429,headers:{'retry-after':'120'}});}};
  await assert.rejects(create(options).search('kokosmelk'),e=>e.retryAfter===120);
  await assert.rejects(create(options).search('rijst'),e=>e.code==='provider_cooldown');
  assert.equal(calls,1);assert.equal(retryDelay(new Date(now+30000).toUTCString(),now),30000);
});
test('pagination exhaustion is explicitly partial and never implies complete cheapest result',async()=>{
  const service=create({maxPages:1,fetcher:async()=>response(1,200,Array(100).fill(raw))});
  const result=await service.search('kokosmelk');assert.equal(result.complete,false);assert.equal(result.reason,'search_limit');
});
test('later-page failure preserves products but reports incompleteness',async()=>{
  let calls=0;const service=create({fetcher:async()=>++calls===1?response(1,200,Array(100).fill(raw)):new Response('',{status:503})});
  const result=await service.search('kokosmelk');assert.equal(result.products.length,100);assert.equal(result.complete,false);
  assert.equal(result.reason,'provider_unavailable');
});
test('detail rejects path traversal and validates upstream payload',async()=>{
  const service=create({fetcher:async url=>{assert.equal(url.pathname,'/api/v1/products/test');return Response.json(raw);}});
  assert.throws(()=>service.detail('../secret'));assert.equal((await service.detail('test')).productId,'test');
});

test('transient retry stays coalesced and consumes a separate persisted budget',async()=>{
  let calls=0;const delays=[],storage=new Storage();
  const service=create({storage,sleep:async ms=>delays.push(ms),fetcher:async()=>++calls===1?new Response('',{status:502}):response()});
  const [a,b]=await Promise.all([service.search('kokosmelk'),service.search('Kokosmelk')]);
  assert.deepEqual(a,b);assert.equal(a.complete,true);assert.equal(calls,2);
  assert.equal((await storage.get('upstream-budget')).daily,2);
  assert.equal(delays.length,1);assert.ok(delays[0]>=300&&delays[0]<500);
});
test('outage retries stop after two attempts and cannot bypass quota',async()=>{
  for(const limit of [1,5]) {
    let calls=0;const service=create({dayLimit:limit,sleep:async()=>{},fetcher:async()=>{calls++;throw new Error('offline');}});
    await assert.rejects(service.search('kokosmelk'),e=>e.code===(limit===1?'daily_budget_exhausted':'provider_unavailable'));
    assert.equal(calls,limit===1?1:2);
  }
});
test('503 Retry-After imposes shared cooldown and authentication failures never retry',async()=>{
  for(const status of [401,403,503]) {
    let calls=0;const service=create({sleep:async()=>assert.fail('must not retry'),fetcher:async()=>{
      calls++;return new Response('',{status,headers:status===503?{'retry-after':'30'}:{}});
    }});
    await assert.rejects(service.search('kokosmelk'),e=>e.code==='provider_unavailable');
    if(status===503) await assert.rejects(service.search('rijst'),e=>e.code==='provider_cooldown'&&e.retryAfter===30);
    assert.equal(calls,1);
  }
});


test('short pages and changing pagination metadata never become complete searches',async()=>{
 const short=create({fetcher:async()=>response(1,200,[raw])});
 const partial=await short.search('kokosmelk');
 assert.equal(partial.products.length,1);assert.equal(partial.complete,false);assert.equal(partial.reason,'invalid_provider_response');
 for(const second of [
  {page:2,page_size:100,total:101,results:[raw]},
  {page:2,page_size:1,total:200,results:[raw]},
 ]){
  let calls=0;const service=create({fetcher:async()=>++calls===1?response(1,200,Array(100).fill(raw)):Response.json(second)});
  const result=await service.search('kokosmelk');
  assert.equal(result.complete,false);assert.equal(result.reason,'invalid_provider_response');assert.equal(calls,2);
  assert.equal(result.products.length,101);
 }
});
