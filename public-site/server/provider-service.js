import {normalizeSearch, normalizeProduct} from '../src/prijsprofeet.js';

export class SourceError extends Error {
  constructor(code, status = 503, retryAfter = 0) {
    super(code); this.code = code; this.status = status; this.retryAfter = retryAfter;
  }
}
export function searchQuery(value) {
  if (typeof value !== 'string') throw new SourceError('invalid_query', 400);
  const query = value.normalize('NFKC').trim().replace(/\s+/g, ' ').toLowerCase();
  if (query.length < 2 || query.length > 100 || !/[\p{L}]/u.test(query) ||
      /[*?<>\x00-\x1f]/.test(query)) throw new SourceError('invalid_query', 400);
  return query;
}
export function retryDelay(value, now) {
  if (value == null) return 60000;
  const seconds = Number(value);
  if (Number.isFinite(seconds) && seconds >= 0) return seconds * 1000;
  const when = Date.parse(value);
  return Number.isFinite(when) ? Math.max(0, when - now) : 60000;
}

/** Instantiate once in the global coordinator, NOT once per edge request or visitor.
 * Persist budget BEFORE dispatch, so restarts cannot reset upstream limits.
 * Storage implements async get(key)/put(key,value); no source payload is persisted here.
 */
export class ProviderService {
  constructor({storage, fetcher = (...args) => fetch(...args), clock = Date.now, key = '', appUrl = '',
    minuteLimit = 90, dayLimit = 5000, concurrency = 3, maxPages = 4,
    sleep = ms => new Promise(resolve => setTimeout(resolve, ms))} = {}) {
    if (!storage) throw new TypeError('Shared storage required');
    this.storage=storage;this.fetcher=fetcher;this.clock=clock;this.key=key;
    this.appUrl=appUrl;this.minuteLimit=minuteLimit;this.dayLimit=dayLimit;
    this.concurrency=concurrency;this.maxPages=maxPages;
    this.sleep=sleep;
    this.active=0;this.inflight=new Map();this.lock=Promise.resolve();
  }
  async reserve() {
    const operation=this.lock.then(async()=>{
      const now=this.clock();
      const prior=await this.storage.get('upstream-budget');
      const state=prior || {requests:[],day:Math.floor(now/86400000),daily:0,cooldown:0};
      state.requests=state.requests.filter(t=>t>now-60000);
      if(state.day!==Math.floor(now/86400000)) {state.day=Math.floor(now/86400000);state.daily=0;}
      if(state.cooldown>now) throw new SourceError('provider_cooldown',429,Math.ceil((state.cooldown-now)/1000));
      if(state.daily>=this.dayLimit) throw new SourceError('daily_budget_exhausted',429,Math.ceil(((state.day+1)*86400000-now)/1000));
      if(state.requests.length>=this.minuteLimit) throw new SourceError('provider_busy',429,Math.ceil((state.requests[0]+60000-now)/1000));
      state.requests.push(now);state.daily++;
      await this.storage.put('upstream-budget',state);
    });
    this.lock=operation.catch(()=>{});return operation;
  }
  async cooldown(delay) {
    const operation=this.lock.then(async()=>{
      const state=await this.storage.get('upstream-budget');
      state.cooldown=Math.max(state.cooldown,this.clock()+delay);
      await this.storage.put('upstream-budget',state);
    });
    this.lock=operation.catch(()=>{});return operation;
  }
  async request(path, params={}) {
    // One bounded retry, inside the same coalesced/concurrency-limited work.
    // Each attempt reserves its own persisted provider budget.
    try {return await this.requestAttempt(path,params);}
    catch(error) {
      if(!error.retryable || error.retryAfter) throw error;
      await this.sleep(300 + Math.floor(Math.random()*200));
      return this.requestAttempt(path,params);
    }
  }
  async requestAttempt(path, params={}) {
    await this.reserve();
    const url=new URL(`https://www.prijsprofeet.nl/api/v1/${path}`);
    for(const [k,v] of Object.entries(params)) url.searchParams.set(k,String(v));
    const headers={'Accept':'application/json','User-Agent':`BoodschappenWijzer/0.1${this.appUrl ? ` (+${this.appUrl})` : ''}`};
    if(this.key) headers['X-API-Key']=this.key;
    let response;
    try {response=await this.fetcher(url,{headers,redirect:'manual',signal:AbortSignal.timeout(15000)});}
    catch {throw Object.assign(new SourceError('provider_unavailable'),{retryable:true});}
    if(response.status===429 || (response.status===503 && response.headers.has('retry-after'))) {
      const delay=retryDelay(response.headers.get('retry-after'),this.clock());
      await this.cooldown(delay);
      throw new SourceError(response.status===429 ? 'provider_rate_limited' : 'provider_unavailable',response.status,Math.max(1,Math.ceil(delay/1000)));
    }
    if(!response.ok) throw Object.assign(new SourceError(response.status===404 ? 'product_not_found' : 'provider_unavailable',response.status===404 ? 404 : 503),
      {retryable:[502,503,504].includes(response.status)});
    // Bound upstream body before JSON parsing; never persist the raw response.
    const reader=response.body?.getReader();
    if(!reader) throw new SourceError('invalid_provider_response');
    let length=0;const chunks=[];
    while(true) {
      const {done,value}=await reader.read();if(done) break;
      length+=value.byteLength;
      if(length>2000000) {await reader.cancel();throw new SourceError('provider_response_too_large');}
      chunks.push(value);
    }
    const bytes=new Uint8Array(length);let offset=0;
    for(const chunk of chunks) {bytes.set(chunk,offset);offset+=chunk.byteLength;}
    try {return JSON.parse(new TextDecoder().decode(bytes));}
    catch {throw new SourceError('invalid_provider_response');}
  }
  coalesce(identity, operation) {
    if(this.inflight.has(identity)) return this.inflight.get(identity);
    if(this.active>=this.concurrency) return Promise.reject(new SourceError('provider_busy',429,2));
    this.active++;
    const work=Promise.resolve().then(operation).finally(()=>{this.active--;this.inflight.delete(identity);});
    this.inflight.set(identity,work);return work;
  }
  search(value) {
    const query=searchQuery(value);
    return this.coalesce(`search:${query}`,async()=>{
      const products=[],rejected=[];let complete=false,total=0,error=null,firstPageSize=null;
      for(let page=1;page<=this.maxPages;page++) {
        let result;
        try {
          result=normalizeSearch(await this.request('search',{q:query,page,page_size:100}),{page,now:this.clock()});
        } catch(e) {
          if(page===1) throw e instanceof SourceError ? e : new SourceError('invalid_provider_response');
          error=e instanceof SourceError ? e.code : 'invalid_provider_response';break;
        }
        products.push(...result.products);rejected.push(...result.rejected);
        const consistent=result.paginationConsistent&&(page===1||(result.total===total&&result.pageSize===firstPageSize));
        if(page===1){total=result.total;firstPageSize=result.pageSize;}
        if(!consistent){error='invalid_provider_response';break;}
        if(!result.hasMore) {complete=true;break;}
      }
      return {query,products,rejected,total,complete,reason:complete ? null : error || 'search_limit',fetchedAt:this.clock()};
    });
  }
  detail(id) {
    if(typeof id!=='string' || !/^[\w-]{1,160}$/.test(id)) throw new SourceError('invalid_product_id',400);
    return this.coalesce(`detail:${id}`,async()=>{
      try {return normalizeProduct(await this.request(`products/${encodeURIComponent(id)}`),{now:this.clock()});}
      catch(e) {throw e instanceof SourceError ? e : new SourceError('invalid_provider_response');}
    });
  }
}
