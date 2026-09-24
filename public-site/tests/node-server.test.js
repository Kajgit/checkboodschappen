import test from 'node:test';
import {request as httpRequest} from 'node:http';
import assert from 'node:assert/strict';
import {mkdtemp,mkdir,writeFile,symlink,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createNodeServer} from '../server/node-server.js';
test('self-host HTTP protects files and shares cache without trusting forged IPs',async()=>{
 const dir=await mkdtemp(join(tmpdir(),'grocery-http-'));let host;
 try{
  const assets=join(dir,'assets');await mkdir(assets);await writeFile(join(assets,'index.html'),'<h1>Test</h1>');
  await writeFile(join(dir,'secret.txt'),'private');await symlink(join(dir,'secret.txt'),join(assets,'leak.txt'));
  host=await createNodeServer({assets,database:join(dir,'state.sqlite'),env:{PUBLIC_APP_URL:'https://app.test',VISITOR_HASH_SECRET:'x'.repeat(32),PRIJSPROFEET_ENABLED:'true'}});
  let calls=0;host.coordinator.service.fetcher=async()=>{calls++;return Response.json({page:1,page_size:100,total:0,results:[]});};
  await new Promise(resolve=>host.server.listen(0,'127.0.0.1',resolve));const url=`http://127.0.0.1:${host.server.address().port}`;
  assert.equal(await (await fetch(url)).text(),'<h1>Test</h1>');
  for(const path of ['/leak.txt','/.env','/state.sqlite'])assert.equal((await fetch(url+path)).status,404);
  const search=(body,extra={})=>fetch(url+'/api/search',{method:'POST',headers:{Origin:'https://app.test','Content-Type':'application/json',...extra},body});
  assert.equal((await search(JSON.stringify({query:'kokosmelk'}),{'CF-Connecting-IP':'192.0.2.1'})).status,200);
  const repeated=await search(JSON.stringify({query:'kokosmelk'}),{'X-Real-IP':'192.0.2.2','X-Forwarded-For':'192.0.2.3'});
  assert.equal((await repeated.json()).cacheHit,true);assert.equal(calls,1);
  assert.equal(host.coordinator.sql.exec('SELECT * FROM visitor_budget').toArray().length,1);
  assert.equal((await search('x'.repeat(2049))).status,413);
  assert.equal((await search('{}',{Origin:'https://evil.test'})).status,403);
 }finally{await host?.close();await rm(dir,{recursive:true,force:true});}
});

test('explicit trusted proxy requires one valid IP and separates visitor budgets',async()=>{
 const dir=await mkdtemp(join(tmpdir(),'grocery-proxy-'));let host;
 try{
  const assets=join(dir,'assets');await mkdir(assets);
  host=await createNodeServer({assets,database:join(dir,'state.sqlite'),trustedProxyIps:['127.0.0.1'],env:{PUBLIC_APP_URL:'https://app.test',VISITOR_HASH_SECRET:'x'.repeat(32),PRIJSPROFEET_ENABLED:'true'}});
  host.coordinator.service.fetcher=async()=>Response.json({page:1,page_size:100,total:0,results:[]});
  await new Promise(resolve=>host.server.listen(0,'127.0.0.1',resolve));const url=`http://127.0.0.1:${host.server.address().port}/api/search`;
  const request=address=>fetch(url,{method:'POST',headers:{Origin:'https://app.test','Content-Type':'application/json',...(address?{'X-Real-IP':address}:{})},body:JSON.stringify({query:'kokosmelk'})});
  for(const address of [undefined,'192.0.2.1, 192.0.2.2','garbage'])assert.equal((await request(address)).status,400);
  for(const address of ['192.0.2.1','192.0.2.2'])assert.equal((await request(address)).status,200);
  assert.equal(host.coordinator.sql.exec('SELECT * FROM visitor_budget').toArray().length,2);
 }finally{await host?.close();await rm(dir,{recursive:true,force:true});}
});

test('shutdown drains an in-flight provider request before releasing database ownership',async()=>{
 const dir=await mkdtemp(join(tmpdir(),'grocery-drain-'));let host,release;
 try{
  const assets=join(dir,'assets');await mkdir(assets);
  host=await createNodeServer({assets,database:join(dir,'state.sqlite'),env:{PUBLIC_APP_URL:'https://app.test',VISITOR_HASH_SECRET:'x'.repeat(32),PRIJSPROFEET_ENABLED:'true'}});
  let entered;const started=new Promise(resolve=>{entered=resolve;});
  const gate=new Promise(resolve=>{release=resolve;});
  host.coordinator.service.fetcher=async()=>{entered();await gate;return Response.json({page:1,page_size:100,total:0,results:[]});};
  await new Promise(resolve=>host.server.listen(0,'127.0.0.1',resolve));
  const pending=fetch(`http://127.0.0.1:${host.server.address().port}/api/search`,{method:'POST',headers:{Origin:'https://app.test','Content-Type':'application/json'},body:JSON.stringify({query:'kokosmelk'})});
  await started;let closed=false;const closing=host.close().then(()=>{closed=true;});
  await new Promise(resolve=>setTimeout(resolve,20));assert.equal(closed,false);
  release();assert.equal((await pending).status,200);await closing;host=null;
  const replacement=await createNodeServer({assets,database:join(dir,'state.sqlite'),env:{PUBLIC_APP_URL:'https://app.test',VISITOR_HASH_SECRET:'x'.repeat(32)}});
  await replacement.close();
 }finally{release?.();await host?.close();await rm(dir,{recursive:true,force:true});}
});

test('disconnected client does not let concurrent shutdown calls close active storage',async()=>{
 const dir=await mkdtemp(join(tmpdir(),'grocery-abort-'));let host,release;
 try{
  const assets=join(dir,'assets');await mkdir(assets);
  host=await createNodeServer({assets,database:join(dir,'state.sqlite'),env:{PUBLIC_APP_URL:'https://app.test',VISITOR_HASH_SECRET:'x'.repeat(32),PRIJSPROFEET_ENABLED:'true'}});
  let enter;const started=new Promise(resolve=>{enter=resolve;});const gate=new Promise(resolve=>{release=resolve;});
  host.coordinator.service.fetcher=async()=>{enter();await gate;return Response.json({page:1,page_size:100,total:0,results:[]});};
  await new Promise(resolve=>host.server.listen(0,'127.0.0.1',resolve));
  const controller=new AbortController();
  const request=fetch(`http://127.0.0.1:${host.server.address().port}/api/search`,{method:'POST',headers:{Origin:'https://app.test','Content-Type':'application/json'},body:JSON.stringify({query:'kokosmelk'}),signal:controller.signal}).catch(error=>error);
  await started;controller.abort();await request;
  const first=host.close(),second=host.close();assert.equal(first,second);
  let done=false;first.then(()=>{done=true;});await new Promise(resolve=>setTimeout(resolve,20));assert.equal(done,false);
  release();await first;host=null;
 }finally{release?.();await host?.close();await rm(dir,{recursive:true,force:true});}
});


test('64 unfinished request bodies trigger backpressure and capacity recovers after disconnect',async()=>{
 const dir=await mkdtemp(join(tmpdir(),'grocery-slow-body-'));let host;const clients=[];
 try{
  const assets=join(dir,'assets');await mkdir(assets);await writeFile(join(assets,'index.html'),'ready');
  host=await createNodeServer({assets,database:join(dir,'state.sqlite'),env:{PUBLIC_APP_URL:'https://app.test',VISITOR_HASH_SECRET:'x'.repeat(32)}});
  await new Promise(resolve=>host.server.listen(0,'127.0.0.1',resolve));
  const port=host.server.address().port;
  for(let i=0;i<64;i++){
   const received=new Promise(resolve=>host.server.once('request',resolve));
   const client=httpRequest({host:'127.0.0.1',port,path:'/api/search',method:'POST',headers:{Origin:'https://app.test','Content-Type':'application/json','Content-Length':'100'}});
   client.on('error',()=>{});clients.push(client);client.write('{');await received;
  }
  const busy=await fetch(`http://127.0.0.1:${port}/`);
  assert.equal(busy.status,503);assert.equal(busy.headers.get('Retry-After'),'1');assert.equal((await busy.json()).error,'service_busy');
  // Request close events occur after the body reader rejects on disconnect.
  const closed=[];for(const client of clients){closed.push(new Promise(resolve=>client.once('close',resolve)));client.destroy();}
  await Promise.all(closed);
  let recovered=false;
  for(let i=0;i<50;i++){const response=await fetch(`http://127.0.0.1:${port}/`);if(response.status===200){assert.equal(await response.text(),'ready');recovered=true;break;}await new Promise(resolve=>setTimeout(resolve,10));}
  assert.equal(recovered,true);
 }finally{for(const client of clients)client.destroy();await host?.close();await rm(dir,{recursive:true,force:true});}
});
