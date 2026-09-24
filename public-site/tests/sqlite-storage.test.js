import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {SqliteStorage} from '../server/sqlite-storage.js';
import worker,{ProviderCoordinator} from '../server/worker.js';

test('self-hosted coordinator preserves cache and upstream budgets across restart',async()=>{
 const directory=await mkdtemp(join(tmpdir(),'grocery-storage-')),path=join(directory,'coordinator.sqlite');
 let storage=new SqliteStorage(path),calls=0;
 const env={VISITOR_HASH_SECRET:'synthetic-only',PUBLIC_APP_URL:'https://app.test',SOURCE_MINUTE_LIMIT:'1'};
 const create=()=>{
  const coordinator=new ProviderCoordinator({storage},env);
  coordinator.service.fetcher=async()=>{calls++;return Response.json({page:1,page_size:100,total:1,results:[{
   product_id:'synthetic',name:'Kokosmelk',retailer:'jumbo',price:2,quantity:'400 ml',promotion_status:'shelf',extracted_at:new Date().toISOString()
  }]});};
  return coordinator;
 };
 const request=(coordinator,value)=>coordinator.fetch(new Request('https://internal/request',{method:'POST',body:JSON.stringify({action:'search',value,visitor:'a'.repeat(64)})}));
 try {
  let coordinator=create();assert.equal((await request(coordinator,'kokosmelk')).status,200);
  assert.ok(await storage.getAlarm());storage.close();storage=new SqliteStorage(path);coordinator=create();
  const cached=await request(coordinator,'kokosmelk');assert.equal(cached.status,200);assert.equal((await cached.json()).cacheHit,true);
  const blocked=await request(coordinator,'havermout');assert.equal(blocked.status,429);assert.equal((await blocked.json()).error,'provider_busy');assert.equal(calls,1);
  storage.sql.exec('UPDATE app_cache SET expires=?',Date.now()-1);
  storage.sql.exec('UPDATE visitor_budget SET day=?',Math.floor(Date.now()/86400000)-1);
  await coordinator.alarm();assert.equal(storage.sql.exec('SELECT * FROM app_cache').toArray().length,0);
  assert.equal(storage.sql.exec('SELECT * FROM visitor_budget').toArray().length,0);assert.equal(await storage.getAlarm(),null);
 } finally {storage.close();await rm(directory,{recursive:true,force:true});}
});


test('clock crossing midnight rotates visitor identity but preserves rolling upstream limits',async t=>{
 const directory=await mkdtemp(join(tmpdir(),'grocery-midnight-'));
 const storage=new SqliteStorage(join(directory,'state.sqlite'));
 const midnight=Date.parse('2026-09-25T00:00:00Z');let now=midnight-1000,calls=0;
 t.mock.method(Date,'now',()=>now);
 const env={VISITOR_HASH_SECRET:'synthetic-only',PUBLIC_APP_URL:'https://app.test',PRIJSPROFEET_ENABLED:'true',SOURCE_MINUTE_LIMIT:'1'};
 const coordinator=new ProviderCoordinator({storage},env);
 coordinator.service.fetcher=async()=>{calls++;return Response.json({page:1,page_size:100,total:0,results:[]});};
 env.COORDINATOR={idFromName:()=> 'single-test-object',get:()=>({fetch:(url,options)=>coordinator.fetch(new Request(url,options))})};
 const request=query=>worker.fetch(new Request('https://app.test/api/search',{method:'POST',headers:{Origin:'https://app.test','Content-Type':'application/json','CF-Connecting-IP':'192.0.2.1'},body:JSON.stringify({query})}),env);
 try {
  assert.equal((await request('kokosmelk')).status,200);
  const before=storage.sql.exec('SELECT * FROM visitor_budget').toArray()[0];
  now=midnight;
  await coordinator.alarm();
  assert.equal(storage.sql.exec('SELECT * FROM visitor_budget').toArray().length,0);
  const warm=await request('kokosmelk');assert.equal((await warm.json()).cacheHit,true);
  const after=storage.sql.exec('SELECT * FROM visitor_budget').toArray()[0];
  assert.notEqual(after.id,before.id);assert.equal(after.day,before.day+1);assert.equal(after.daily,1);
  const limited=await request('rijst');assert.equal(limited.status,429);
  assert.equal((await limited.json()).error,'provider_busy');assert.equal(limited.headers.get('retry-after'),'59');
  assert.equal(calls,1);
  now=midnight+59000;
  assert.equal((await request('rijst')).status,200);assert.equal(calls,2);
  const upstream=await storage.get('upstream-budget');
  assert.equal(upstream.daily,1);assert.deepEqual(upstream.requests,[now]);
  const traffic=storage.sql.exec('SELECT * FROM traffic_budget').toArray()[0];
  assert.equal(traffic.count,3);assert.equal(traffic.day,Math.floor(midnight/86400000));
 } finally {storage.close();await rm(directory,{recursive:true,force:true});}
});
