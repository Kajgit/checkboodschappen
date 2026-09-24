import {createServer} from 'node:http';
import {createReadStream} from 'node:fs';
import {realpath,stat} from 'node:fs/promises';
import {resolve,sep,extname,dirname,basename,join as joinPath} from 'node:path';
import {isIP} from 'node:net';
import {pipeline} from 'node:stream/promises';
import worker from './worker.js';
import {createCoordinatorHost} from './coordinator-host.js';

const types={'.png':'image/png','.woff2':'font/woff2','.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.mjs':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.json':'application/json','.wasm':'application/wasm','.zip':'application/zip','.txt':'text/plain; charset=utf-8'};
const ip=value=>value?.startsWith('::ffff:')?value.slice(7):value;
function bodyOf(request){return new Promise((resolve,reject)=>{
 let length=0,over=false;const chunks=[];
 request.on('data',chunk=>{length+=chunk.length;if(length>2048){if(!over){over=true;reject(Object.assign(new Error('request_too_large'),{status:413}));}return;}chunks.push(chunk);});
 request.on('end',()=>{if(!over)resolve(Buffer.concat(chunks));});request.on('error',reject);
});}
/** Dedicated static build directory and private database directory are required.
 * One process only. TLS belongs at the operator's reverse proxy.
 */
export async function createNodeServer({assets,database,env,trustedProxyIps=[],onError=()=>{}}){
 const origin=new URL(env.PUBLIC_APP_URL);
 if(!['http:','https:'].includes(origin.protocol)||origin.username||origin.password||origin.pathname!=='/'||origin.search||origin.hash)throw new Error('PUBLIC_APP_URL must be an origin');
 if(!env.VISITOR_HASH_SECRET||env.VISITOR_HASH_SECRET.length<32)throw new Error('A private VISITOR_HASH_SECRET of at least 32 characters is required');
 const root=await realpath(assets);
 let db;try{db=await realpath(database);}catch(error){if(error.code!=='ENOENT')throw error;db=joinPath(await realpath(dirname(resolve(database))),basename(database));}
 if(db===root||db.startsWith(root+sep))throw new Error('Database must be outside public assets');
 const trusted=new Set(trustedProxyIps.map(ip));if([...trusted].some(value=>!isIP(value)))throw new Error('Trusted proxies must be explicit IP addresses');
 const host=await createCoordinatorHost(database,env,{onError});let active=0,closing;const drained=[];
 const runtimeEnv={...env,COORDINATOR:{idFromName:()=> 'global-provider-v1',get:()=>({fetch:(url,options)=>host.coordinator.fetch(new Request(url,options))})}};
 const server=createServer(async(request,response)=>{
  const fail=(status,error)=>{if(!response.headersSent){response.writeHead(status,{'Content-Type':'application/json','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'});response.end(JSON.stringify({error}));}};
  if(++active>64){active--;response.setHeader('Retry-After','1');request.resume();fail(503,'service_busy');return;}
  try {
   if(!request.url?.startsWith('/')||request.url.startsWith('//')){fail(400,'invalid_request');return;}
   const url=new URL(request.url,origin);
   if(url.pathname.startsWith('/api/')){
    let address=ip(request.socket.remoteAddress);
    if(trusted.has(address)){
     address=request.headers['x-real-ip'];
     if(typeof address!=='string'||!isIP(address)){fail(400,'invalid_proxy_address');return;}
     address=ip(address);
    }
    // Ignore CF-Connecting-IP / Forwarded / X-Forwarded-For supplied by clients.
    const headers=new Headers();for(const name of ['origin','content-type'])if(typeof request.headers[name]==='string')headers.set(name,request.headers[name]);
    headers.set('CF-Connecting-IP',address||'');
    const body=['GET','HEAD'].includes(request.method)?undefined:await bodyOf(request);
    const result=await worker.fetch(new Request(url,{method:request.method,headers,body}),runtimeEnv);
    response.writeHead(result.status,Object.fromEntries(result.headers));response.end(Buffer.from(await result.arrayBuffer()));
   } else {
    request.resume();if(!['GET','HEAD'].includes(request.method)){fail(405,'method_not_allowed');return;}
    let pathname;try{pathname=decodeURIComponent(url.pathname);}catch{fail(400,'invalid_path');return;}
    if(pathname.includes('\\')||pathname.split('/').some(part=>part.startsWith('.'))){fail(404,'not_found');return;}
    let file;try{file=await realpath(resolve(root,'.'+(pathname==='/'?'/index.html':['/roadmap','/roadmap/'].includes(pathname)?'/roadmap.html':pathname)));}catch{fail(404,'not_found');return;}
    if(!file.startsWith(root+sep)||!types[extname(file)]){fail(404,'not_found');return;}
    const info=await stat(file);if(!info.isFile()){fail(404,'not_found');return;}
    response.writeHead(200,{'Content-Type':types[extname(file)],'Content-Length':info.size,'Cache-Control':'no-cache','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer'});
    if(request.method==='HEAD')response.end();else await pipeline(createReadStream(file),response);
   }
  }catch(error){fail(error.status||503,error.status===413?'request_too_large':'service_unavailable');}
  finally{active--;if(!active)for(const done of drained.splice(0))done();}
 });
 server.requestTimeout=15000;server.headersTimeout=10000;server.keepAliveTimeout=5000;
 return {server,coordinator:host.coordinator,close(){
  if(closing)return closing;
  closing=(async()=>{
  if(server.listening)await new Promise((resolve,reject)=>server.close(error=>error?reject(error):resolve()));
  if(active)await new Promise(resolve=>drained.push(resolve));
  await host.close();
  })();return closing;
 }};
}
