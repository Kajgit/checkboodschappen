import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {setTimeout as delay} from 'node:timers/promises';
import {SqliteStorage} from '../server/sqlite-storage.js';
import {createCoordinatorHost} from '../server/coordinator-host.js';
const env={VISITOR_HASH_SECRET:'synthetic-only',PUBLIC_APP_URL:'https://app.test'};
test('single owner and scheduled cleanup without incoming requests',async()=>{
 const dir=await mkdtemp(join(tmpdir(),'grocery-owner-')),path=join(dir,'state.sqlite');let host;
 try {
  host=await createCoordinatorHost(path,env,{pollMs:10});
  await assert.rejects(createCoordinatorHost(path,env),/locked/);
  host.storage.sql.exec('INSERT INTO app_cache VALUES(?,?,?)','expired',Date.now()-1,'{}');
  await host.storage.setAlarm(Date.now());
  const deadline=Date.now()+2000;
  while((await host.storage.getAlarm())!==null&&Date.now()<deadline)await delay(20);
  assert.equal(await host.storage.getAlarm(),null);
  assert.equal(host.storage.sql.exec('SELECT * FROM app_cache').toArray().length,0);
  await host.close();host=await createCoordinatorHost(path,env);await host.close();host=null;
  await writeFile(path+'.lock','{"pid":99999999}');
  await assert.rejects(createCoordinatorHost(path,env),/locked/);
 } finally {await host?.close();await rm(dir,{recursive:true,force:true});}
});

test('startup removes expired rows even when no alarm was persisted',async()=>{
 const dir=await mkdtemp(join(tmpdir(),'grocery-startup-')),path=join(dir,'state.sqlite');let host;
 try {
  host=await createCoordinatorHost(path,env);await host.close();host=null;
  const storage=new SqliteStorage(path);
  storage.sql.exec('INSERT INTO app_cache VALUES(?,?,?)','old',Date.now()-1,'{}');storage.close();
  host=await createCoordinatorHost(path,env);
  assert.equal(host.storage.sql.exec('SELECT * FROM app_cache').toArray().length,0);
 } finally {await host?.close();await rm(dir,{recursive:true,force:true});}
});
