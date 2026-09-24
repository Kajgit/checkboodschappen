import {open,realpath,unlink} from 'node:fs/promises';
import {dirname,basename,join} from 'node:path';
import {SqliteStorage} from './sqlite-storage.js';
import {ProviderCoordinator} from './worker.js';

/** One local process per database. Crash locks fail closed; never steal a lock. */
export async function createCoordinatorHost(path,env,{pollMs=1000,onError=()=>{}}={}) {
 if(!Number.isInteger(pollMs)||pollMs<10)throw new TypeError('Invalid cleanup interval');
 let canonical;
 try {canonical=await realpath(path);}
 catch(error){if(error.code!=='ENOENT')throw error;canonical=join(await realpath(dirname(path)),basename(path));}
 const lockPath=canonical+'.lock';
 let lock;
 try {lock=await open(lockPath,'wx',0o600);}
 catch(error){if(error.code==='EEXIST')throw new Error('Coordinator is locked. Stop the other process; inspect a crash lock before removing it.');throw error;}
 let storage,timer,running=null,closed=false;
 try {
  await lock.writeFile(JSON.stringify({pid:process.pid,startedAt:new Date().toISOString()})+'\n');
  storage=new SqliteStorage(canonical);
  const coordinator=new ProviderCoordinator({storage},env);
  // Reconcile retention after downtime even if a persisted alarm was missing.
  await coordinator.alarm();
  const tick=()=>{
   if(closed||running)return;
   running=(async()=>{
    const due=await storage.getAlarm();
    if(due!==null&&due<=Date.now())await coordinator.alarm();
   })().catch(()=>onError('Coordinator cleanup failed')).finally(()=>{running=null;});
  };
  timer=setInterval(tick,pollMs);timer.unref();
  return {coordinator,storage,async close(){
   if(closed)return;closed=true;clearInterval(timer);if(running)await running;
   // The HTTP host must drain active requests before calling close.
   try {storage.close();} finally {await lock.close();await unlink(lockPath);}
  }};
 } catch(error){clearInterval(timer);try{storage?.close();}finally{await lock.close();await unlink(lockPath);}throw error;}
}
