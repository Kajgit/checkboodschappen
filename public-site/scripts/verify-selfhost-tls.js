/** Local-only reverse-proxy boundary check. Requires OpenSSL; never changes OS trust. */
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {mkdtemp,mkdir,writeFile,readFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createServer as httpsServer,request as httpsRequest} from 'node:https';
import {request as httpRequest} from 'node:http';
import {createNodeServer} from '../server/node-server.js';
const dir=await mkdtemp(join(tmpdir(),'grocery-tls-'));let host,proxy,backendPort;
try {
 const config=join(dir,'openssl.cnf'),key=join(dir,'key.pem'),certPath=join(dir,'cert.pem');
 await writeFile(config,'[req]\nprompt=no\ndistinguished_name=dn\nx509_extensions=ext\n[dn]\nCN=localhost\n[ext]\nsubjectAltName=DNS:localhost,IP:127.0.0.1\nbasicConstraints=critical,CA:TRUE\n');
 execFileSync('openssl',['req','-x509','-newkey','rsa:2048','-nodes','-days','1','-config',config,'-keyout',key,'-out',certPath],{stdio:'ignore',timeout:15000});
 const cert=await readFile(certPath);
 proxy=httpsServer({key:await readFile(key),cert},(incoming,outgoing)=>{
  const headers={...incoming.headers,'x-real-ip':incoming.socket.remoteAddress};
  for(const name of ['forwarded','x-forwarded-for','cf-connecting-ip'])delete headers[name];
  const upstream=httpRequest({hostname:'127.0.0.1',port:backendPort,path:incoming.url,method:incoming.method,headers},response=>{outgoing.writeHead(response.statusCode,response.headers);response.pipe(outgoing);});
  upstream.on('error',()=>{outgoing.writeHead(502);outgoing.end();});incoming.pipe(upstream);
 });
 await new Promise(resolve=>proxy.listen(0,'127.0.0.1',resolve));
 const port=proxy.address().port,origin=`https://127.0.0.1:${port}`;
 const assets=join(dir,'assets');await mkdir(assets);await writeFile(join(assets,'index.html'),'TLS fixture');
 host=await createNodeServer({assets,database:join(dir,'state.sqlite'),trustedProxyIps:['127.0.0.1'],env:{PUBLIC_APP_URL:origin,VISITOR_HASH_SECRET:'synthetic-local-test-secret'.repeat(2),PRIJSPROFEET_ENABLED:'true'}});
 let calls=0;host.coordinator.service.fetcher=async()=>{calls++;return Response.json({page:1,page_size:100,total:0,results:[]});};
 await new Promise(resolve=>host.server.listen(0,'127.0.0.1',resolve));backendPort=host.server.address().port;
 function request({trust=true,path='/api/search',headers={}}={}){return new Promise((resolve,reject)=>{
  const req=httpsRequest({hostname:'127.0.0.1',port,path,method:'POST',agent:false,...(trust?{ca:cert}:{}),headers:{Origin:origin,'Content-Type':'application/json',...headers}},res=>{
   let body='';res.setEncoding('utf8');res.on('data',chunk=>{body+=chunk;});res.on('end',()=>resolve({status:res.statusCode,body:JSON.parse(body)}));
  });req.on('error',reject);req.end(JSON.stringify({query:'kokosmelk'}));
 });}
 await assert.rejects(request({trust:false}),error=>['DEPTH_ZERO_SELF_SIGNED_CERT','SELF_SIGNED_CERT_IN_CHAIN'].includes(error.code));
 for(const address of ['192.0.2.1','198.51.100.9'])assert.equal((await request({headers:{'X-Real-IP':address,'X-Forwarded-For':address,'CF-Connecting-IP':address,Forwarded:`for=${address}`}})).status,200);
 assert.equal(calls,1);assert.equal(host.coordinator.sql.exec('SELECT * FROM visitor_budget').toArray().length,1);
 assert.equal((await request({headers:{Origin:'https://untrusted.test'}})).status,403);
 const direct=await fetch(`http://127.0.0.1:${backendPort}/api/search`,{method:'POST',headers:{Origin:origin,'Content-Type':'application/json'},body:'{"query":"kokosmelk"}'});
 assert.equal(direct.status,400);
 console.log(JSON.stringify({scope:'Local synthetic HTTPS reverse proxy, not deployed proxy/certificate/load verification',certificateValidation:true,forgedForwardingHeadersIgnored:true,visitorRows:1,upstreamCalls:calls,wrongOriginStatus:403,directMissingProxyHeaderStatus:400}));
} finally {
 if(proxy?.listening)await new Promise(resolve=>proxy.close(resolve));
 await host?.close();await rm(dir,{recursive:true,force:true});
}
