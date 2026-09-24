import test from 'node:test';
import assert from 'node:assert/strict';
import {summarize,runComparison} from '../src/comparison.js';
import {normalizeCatalogue} from '../src/checkjebon.js';
const now=Date.now();
const product=(retailer,price=100)=>({retailer,name:'Rijst',priceCents:price,eligible:true,issues:[],expiresAt:now+100000});
const accepted=(retailer,price=100)=>({product:product(retailer,price),decision:{status:'accepted',packages:1,overage:0}});
const items=[{id:'1',query:'rijst'},{id:'2',query:'melk'}];
test('complete basket outranks cheaper incomplete basket',()=>{
 const result=summarize(items,[{candidates:[accepted('A'),accepted('B',200)]},{candidates:[accepted('B',200)]}],{now});
 assert.equal(result.baskets[0].retailer,'B');assert.equal(result.baskets[0].complete,true);assert.equal(result.baskets[1].totalCents,100);
});
test('uncertain identity and stale price never contribute to a complete total',()=>{
 const result=summarize(items,[{candidates:[{...accepted('A'),decision:{status:'unreviewed',reason:'Controleer product'}}]},
 {candidates:[{...accepted('A'),product:{...product('A'),expiresAt:now-1}}]}],{now});
 assert.equal(result.baskets[0].lines.length,0);assert.equal(result.baskets[0].missing.length,2);
});
test('duplicate queries are fetched once but remain two requested lines',async()=>{
 let calls=0;const list=[{id:'1',query:'rijst'},{id:'2',query:'rijst'}];
 const matcher={request:async action=>action==='load'?{}:{candidates:[accepted('A')]}};
 const result=await runComparison(list,{products:[],expiresAt:now+100000},matcher,{search:async()=>{calls++;return {products:[],complete:true};}});
 assert.equal(calls,1);assert.equal(result.baskets[0].lines.length,2);assert.equal(result.baskets[0].totalCents,200);
});
test('disabled provider produces explicit incomplete search and avoids repeated calls',async()=>{
 let calls=0;const error=new Error('Source disabled');error.code='source_not_enabled';
 const matcher={request:async action=>action==='load'?{}:{candidates:[accepted('A')]}};
 const result=await runComparison(items,{products:[],expiresAt:now+100000},matcher,{search:async()=>{calls++;throw error;}});
 assert.equal(calls,1);assert.equal(result.searchComplete,false);assert.deepEqual(result.sourceIssues,['Source disabled']);
});
test('Checkjebon normalization rejects bad money and preserves precise hutspot facts only',()=>{
 const catalogue=normalizeCatalogue([{n:'ah',d:[{n:'AH Hutspot',l:'wi80568/ah-hutspot',s:'1 kg',p:2},
 {n:'Hutspot maaltijd',l:'other',s:'500 g',p:3},{n:'Rijst',p:NaN}]}],{now});
 assert.equal(catalogue.products.length,2);assert.equal(catalogue.rejected,1);
 assert.equal(catalogue.products[0].category,'groente');assert.equal(catalogue.products[1].category,undefined);
 assert.equal(catalogue.products[0].priceCents,200);
});

test('quota cooldown is explained and stops the remaining list requests',async()=>{
 const {searchPrijsProfeet}=await import('../src/comparison.js');let calls=0;
 const search=(query,options)=>searchPrijsProfeet(query,{...options,fetcher:async()=>{
  calls++;return Response.json({error:'provider_rate_limited'},{status:429,headers:{'Retry-After':'125'}});
 }});
 const matcher={request:async action=>action==='load'?{}:{candidates:[accepted('A')]}};
 const result=await runComparison(items,{products:[],expiresAt:now+100000},matcher,{search});
 assert.equal(calls,1);assert.equal(result.searchComplete,false);
 assert.match(result.sourceIssues[0],/3 minuten/);assert.match(result.sourceIssues[0],/Vergelijk boodschappen/);
 assert.equal(result.baskets[0].lines.length,2);
});
test('platform HTML failures and network outages are bounded for large lists',async()=>{
 const {searchPrijsProfeet}=await import('../src/comparison.js');
 for(const fail of [()=>new Response('<html>Unavailable</html>',{status:503}),()=>{throw new TypeError('offline');}]) {
  let calls=0;
  const matcher={request:async action=>action==='load'?{}:{candidates:[]}};
  const result=await runComparison(Array.from({length:44},(_,i)=>({id:String(i),query:`product ${i}`})),
   {products:[],expiresAt:now+100000},matcher,{search:(q,o)=>searchPrijsProfeet(q,{...o,fetcher:async()=>{calls++;return fail();}})});
  assert.equal(calls,1);assert.equal(result.searchComplete,false);assert.match(result.sourceIssues[0],/Probeer later/);
 }
});
test('source request cancellation remains cancellation rather than outage',async()=>{
 const {searchPrijsProfeet}=await import('../src/comparison.js');const controller=new AbortController();controller.abort();
 await assert.rejects(searchPrijsProfeet('rijst',{signal:controller.signal,fetcher:async()=>{throw controller.signal.reason;}}),e=>e.name==='AbortError');
});

test('catalogue timestamp is not confused with retrieval or individual price observation',async()=>{
 const raw=[{n:'ah',d:[{n:'Rijst',s:'1 kg',p:2}]}];
 const stale=normalizeCatalogue(raw,{now,modified:new Date(now-86400001).toUTCString()});
 assert.equal(stale.products[0].eligible,false);
 const future=normalizeCatalogue(raw,{now,modified:new Date(now+3600000).toUTCString()});
 assert.equal(future.products[0].eligible,false);assert.match(future.sourceIssues[0],/toekomst/);
 for(const modified of [null,'invalid']) {
  const unknown=normalizeCatalogue(raw,{now,modified});
  assert.equal(unknown.modified,null);assert.equal(unknown.products[0].timestampKind,'catalogue');
  const result=await runComparison([items[0]],unknown,{request:async action=>action==='load'?{}:{candidates:[accepted('A')]}},
   {search:async()=>({products:[],complete:true})});
  assert.equal(result.searchComplete,false);assert.match(result.sourceIssues[0],/ouderdom/);
 }
 const fresh=normalizeCatalogue(raw,{now,modified:new Date(now-1000).toUTCString()});
 assert.equal(fresh.products[0].eligible,true);assert.deepEqual(fresh.sourceIssues,[]);
});

test('baseline outage still searches the other source and marks results incomplete',async()=>{
 const {loadAvailableCatalogue}=await import('../src/checkjebon.js');
 const catalogue=await loadAvailableCatalogue({fetcher:async()=>new Response('unavailable',{status:503})});
 let searches=0;
 const matcher={request:async(action,args)=>action==='load'?{}:{candidates:args.extra.map(product=>({product,decision:{status:'accepted',packages:1,overage:0}}))}};
 const result=await runComparison(items,catalogue,matcher,{search:async()=>{searches++;return {complete:true,products:[product('A')]};}});
 assert.equal(searches,2);assert.equal(result.baskets[0].lines.length,2);
 assert.equal(result.searchComplete,false);assert.match(result.sourceIssues[0],/Checkjebon is niet beschikbaar/);
});
test('baseline cancellation does not become an outage fallback',async()=>{
 const {loadAvailableCatalogue}=await import('../src/checkjebon.js');const controller=new AbortController();controller.abort();
 await assert.rejects(loadAvailableCatalogue({signal:controller.signal,fetcher:async()=>{throw controller.signal.reason;}}),e=>e.name==='AbortError');
});

test('complete multibuy groups compete on payable total and retain extra quantity',()=>{
 const item={id:'bulk',query:'kokosmelk',quantity:1000,unit:'ml'};
 const decision={status:'accepted',packages:3,packageAmount:400,desired:1000,dimension:'volume',overage:200};
 const multi={...product('A'),multiBuy:{quantity:2,priceCents:250}};
 const result=summarize([item],[{candidates:[{product:multi,decision},{product:product('A',200),decision}]}],{now});
 const line=result.baskets[0].lines[0];
 assert.equal(line.totalCents,500);assert.equal(line.decision.packages,4);
 assert.equal(line.decision.overage,600);assert.equal(line.decision.promotionExtraPackages,1);
 assert.equal(decision.packages,3);assert.equal(decision.overage,200);
 const capped=summarize([item],[{candidates:[{product:{...multi,maxPerCustomer:3},decision},{product:product('A',200),decision}]}],{now});
 assert.equal(capped.baskets[0].lines[0].totalCents,600);
 const cheaper=summarize([item],[{candidates:[{product:multi,decision},{product:product('A',100),decision}]}],{now});
 assert.equal(cheaper.baskets[0].lines[0].totalCents,300);
 assert.equal(cheaper.baskets[0].lines[0].decision.packages,3);
});

test('member selection changes payable total and receipt label only with opt-in',async()=>{
 const {normalizeProduct}=await import('../src/prijsprofeet.js');
 const {receiptRows}=await import('../src/receipt-model.js');
 const p=normalizeProduct({product_id:'member-example',retailer:'lidl',name:'Rijst',price:2,loyalty_price:1.5,loyalty_program:'Testkaart',quantity:'500 g',promotion_status:'shelf',extracted_at:new Date(now).toISOString()},{now});
 const item={id:'member',query:'rijst',quantity:1,unit:'verpakking'};
 for(const loyalty of [false,true]){
  const result=summarize([item],[{candidates:[{product:p,decision:{status:'accepted',packages:1,overage:0}}]}],{now,loyalty});
  const basket=result.baskets[0];assert.equal(basket.totalCents,loyalty?150:200);
  assert.equal(basket.lines[0].product.loyaltyRequired,loyalty);
  assert.equal(receiptRows(basket,result).some(row=>row.text.includes('Ledenprijs: klantenkaart vereist (Testkaart)')),loyalty);
 }
 assert.equal(p.priceCents,200);assert.equal(p.loyaltyRequired,false);
});
