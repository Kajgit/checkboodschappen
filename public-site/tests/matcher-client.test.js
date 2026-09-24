import test from 'node:test';
import assert from 'node:assert/strict';
import {MatcherClient} from '../src/matcher-client.js';
class WorkerStub {
 terminated=0;messages=[];
 postMessage(message){this.messages.push(message);if(this.throwOnSend)throw new Error('clone failed');}
 terminate(){this.terminated++;}
}
function installWorker(t){
 const previous=Object.getOwnPropertyDescriptor(globalThis,'Worker');
 Object.defineProperty(globalThis,'Worker',{value:WorkerStub,writable:true,configurable:true});
 t.after(()=>{if(previous)Object.defineProperty(globalThis,'Worker',previous);else delete globalThis.Worker;});
}

test('startup failure before any request rejects future work immediately',async(t)=>{
 installWorker(t);
 const client=new MatcherClient();client.worker.onerror();
 await assert.rejects(client.request('load',{products:[]}),/niet starten/);
 assert.equal(client.pending.size,0);assert.equal(client.worker.messages.length,0);
 client.close();assert.equal(client.worker.terminated,1);
});

test('transport failures reject all outstanding requests and clear their timers',async(t)=>{
 installWorker(t);
 const client=new MatcherClient();const first=client.request('match',{});const second=client.request('match',{});
 const checks=[assert.rejects(first,/resultaat niet verwerken/),assert.rejects(second,/resultaat niet verwerken/)];
 client.worker.onmessageerror();await Promise.all(checks);
 assert.equal(client.pending.size,0);assert.equal(client.worker.terminated,1);
 await assert.rejects(client.request('match',{}),/resultaat niet verwerken/);
});

test('synchronous send failure closes the worker without leaving pending work',async(t)=>{
 installWorker(t);
 const client=new MatcherClient();client.worker.throwOnSend=true;
 await assert.rejects(client.request('load',{}),/clone failed/);
 assert.equal(client.pending.size,0);assert.equal(client.worker.terminated,1);
});
