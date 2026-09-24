import {ProviderService, SourceError, searchQuery} from './provider-service.js';
const json = (body,status=200,extra={})=>Response.json(body,{status,headers:{
  'Cache-Control':'no-store','X-Content-Type-Options':'nosniff',...extra}});
function fail(error) {
  return json({error:error instanceof SourceError ? error.code : 'service_unavailable'},
    error instanceof SourceError ? error.status : 503,
    error.retryAfter ? {'Retry-After':String(error.retryAfter)} : {});
}
async function digest(value,secret) {
  const key=await crypto.subtle.importKey('raw',new TextEncoder().encode(secret),{name:'HMAC',hash:'SHA-256'},false,['sign']);
  const signature=await crypto.subtle.sign('HMAC',key,new TextEncoder().encode(value));
  return [...new Uint8Array(signature)].map(b=>b.toString(16).padStart(2,'0')).join('');
}
function limit(value,fallback) {const n=Number(value);return Number.isInteger(n)&&n>0?Math.min(n,fallback):fallback;}
async function readBody(request) {
  const reader=request.body?.getReader();if(!reader) throw new SourceError('invalid_request',400);
  const decoder=new TextDecoder();let body='',length=0;
  while(true) {const {done,value}=await reader.read();if(done)break;length+=value.byteLength;
    if(length>2048) {await reader.cancel();throw new SourceError('request_too_large',413);}body+=decoder.decode(value,{stream:true});}
  body+=decoder.decode();
  try{return JSON.parse(body);}catch{throw new SourceError('invalid_request',400);}
}
export default {
  async fetch(request,env) {
    const url=new URL(request.url);
    if(!url.pathname.startsWith('/api/')) return env.ASSETS ? env.ASSETS.fetch(request) : new Response('Not found',{status:404});
    if(!['/api/search','/api/product'].includes(url.pathname)) return json({error:'not_found'},404);
    if(request.method!=='POST') return json({error:'method_not_allowed'},405,{Allow:'POST'});
    if(request.headers.get('Origin')!==url.origin || request.headers.get('Content-Type')?.split(';')[0]!=='application/json') return json({error:'invalid_origin_or_type'},403);
    if(env.PRIJSPROFEET_ENABLED!=='true') return json({error:'source_not_enabled'},503);
    if(!env.VISITOR_HASH_SECRET || !env.PUBLIC_APP_URL) return json({error:'server_not_configured'},503);
    try {
      const data=await readBody(request);
      if(!data || typeof data!=='object' || Array.isArray(data)) throw new SourceError('invalid_request',400);
      const action=url.pathname==='/api/search'?'search':'detail';
      const value=action==='search'?searchQuery(data.query):data.id;
      if(action==='detail' && (typeof value!=='string'||! /^[\w-]{1,160}$/.test(value))) throw new SourceError('invalid_product_id',400);
      const ip=request.headers.get('CF-Connecting-IP');
      if(!ip) throw new SourceError('visitor_unavailable',503);
      const visitor=await digest(`${Math.floor(Date.now()/86400000)}:${ip}`,env.VISITOR_HASH_SECRET);
      const id=env.COORDINATOR.idFromName('global-provider-v1');
      return await env.COORDINATOR.get(id).fetch('https://coordinator.internal/request',{
        method:'POST',body:JSON.stringify({action,value,visitor})});
    } catch(error) {return fail(error);}
  }
};

/** One named object across every edge region: source budgets must never be per isolate. */
export class ProviderCoordinator {
  constructor(ctx,env) {
    this.ctx=ctx;this.env=env;this.sql=ctx.storage.sql;
    this.sql.exec('CREATE TABLE IF NOT EXISTS visitor_budget (id TEXT PRIMARY KEY, day INTEGER, daily INTEGER, window INTEGER, count INTEGER)');
    this.sql.exec('CREATE TABLE IF NOT EXISTS app_cache (key TEXT PRIMARY KEY, expires INTEGER, value TEXT)');
    this.sql.exec('CREATE TABLE IF NOT EXISTS traffic_budget (id INTEGER PRIMARY KEY, day INTEGER, count INTEGER)');
    // Cleanup and MIN/order queries must not scan every retained visitor/cache
    // row per request: SQLite row reads count toward the free daily allowance.
    this.sql.exec('CREATE INDEX IF NOT EXISTS visitor_budget_day ON visitor_budget(day)');
    this.sql.exec('CREATE INDEX IF NOT EXISTS app_cache_expires ON app_cache(expires)');
    this.service=new ProviderService({storage:ctx.storage,key:env.PRIJSPROFEET_API_KEY||'',appUrl:env.PUBLIC_APP_URL,
      minuteLimit:limit(env.SOURCE_MINUTE_LIMIT,90),dayLimit:limit(env.SOURCE_DAY_LIMIT,5000)});
  }
  admit(visitor) {
    const now=Date.now(),day=Math.floor(now/86400000),window=Math.floor(now/3600000);
    const global=this.sql.exec('SELECT * FROM traffic_budget WHERE id=1').toArray()[0];
    if(global?.day===day && global.count>=6000) throw new SourceError('daily_budget_exhausted',429,Math.ceil(((day+1)*86400000-now)/1000));
    this.sql.exec('INSERT OR REPLACE INTO traffic_budget VALUES(1,?,?)',day,global?.day===day?global.count+1:1);
    this.sql.exec('DELETE FROM visitor_budget WHERE day < ?',day);
    const prior=this.sql.exec('SELECT * FROM visitor_budget WHERE id=?',visitor).toArray()[0];
    const daily=prior?.day===day?prior.daily:0,count=prior?.window===window?prior.count:0;
    if(daily>=200||count>=120) throw new SourceError('visitor_budget_exhausted',429,
      Math.ceil(((daily>=200?(day+1)*86400000:(window+1)*3600000)-now)/1000));
    this.sql.exec('INSERT OR REPLACE INTO visitor_budget VALUES(?,?,?,?,?)',visitor,day,daily+1,window,count+1);
  }
  async fetch(request) {
    try {
      const {action,value,visitor}=await request.json();
      if(!['search','detail'].includes(action)||! /^[a-f0-9]{64}$/.test(visitor)) throw new SourceError('invalid_request',400);
      this.admit(visitor);
      // Even a failed upstream call creates visitor state that must expire
      // without relying on another visitor returning tomorrow.
      await this.scheduleCleanup();
      const now=Date.now();
      this.sql.exec('DELETE FROM app_cache WHERE expires <= ?',now);
      const cacheKey=await digest(`${action}:${value}`,this.env.VISITOR_HASH_SECRET);
      const cached=this.sql.exec('SELECT value FROM app_cache WHERE key=?',cacheKey).toArray()[0];
      if(cached) return json({...JSON.parse(cached.value),cacheHit:true});
      const result=action==='search'?await this.service.search(value):await this.service.detail(value);
      const products=action==='search'?result.products:[result];
      const expires=Math.min(now+300000,...products.map(p=>p.expiresAt));
      const encoded=JSON.stringify(result);
      // Only normalized application objects are cached, never raw upstream HTTP responses.
      if(expires>now&&encoded.length<100000&&(action!=='search'||result.complete)) {
        this.sql.exec('INSERT OR REPLACE INTO app_cache VALUES(?,?,?)',cacheKey,expires,encoded);
        this.sql.exec('DELETE FROM app_cache WHERE key IN (SELECT key FROM app_cache ORDER BY expires DESC LIMIT -1 OFFSET 200)');
        await this.scheduleCleanup();
      }
      return json({...result,cacheHit:false});
    } catch(error) {return fail(error);}
  }
  async alarm() {
    this.sql.exec('DELETE FROM app_cache WHERE expires <= ?',Date.now());
    this.sql.exec('DELETE FROM visitor_budget WHERE day < ?',Math.floor(Date.now()/86400000));
    await this.scheduleCleanup();
  }
  async scheduleCleanup() {
    const cacheExpiry=this.sql.exec('SELECT MIN(expires) AS expiry FROM app_cache').toArray()[0]?.expiry;
    const visitorDay=this.sql.exec('SELECT MIN(day) AS day FROM visitor_budget').toArray()[0]?.day;
    const deadlines=[cacheExpiry,visitorDay==null?null:(visitorDay+1)*86400000].filter(value=>value!=null);
    if(!deadlines.length) {await this.ctx.storage.deleteAlarm();return;}
    const next=Math.max(Date.now()+1000,Math.min(...deadlines));
    const current=await this.ctx.storage.getAlarm();
    if(current===null||current<=Date.now()||next<current)await this.ctx.storage.setAlarm(next);
  }
}
