import test from 'node:test';
import assert from 'node:assert/strict';
import {addStoreCombinations} from '../src/store-combinations.js';
const origin={lat:52,lon:5};
const item=id=>({id,query:id,quantity:1,unit:'verpakking'});
function basket(retailer,prices,lon=5.01){const lines=Object.entries(prices).filter(([,price])=>price!==null).map(([id,totalCents])=>({item:item(id),product:{retailer},totalCents}));
 const missing=Object.entries(prices).filter(([,price])=>price===null).map(([id])=>({item:item(id),reason:'Geen passende brondata'}));
 return {retailer,lines,missing,complete:missing.length===0,totalCents:lines.reduce((sum,l)=>sum+l.totalCents,0),travelCents:0,
 totalWithTravelCents:lines.reduce((sum,l)=>sum+l.totalCents,0),store:{retailer,name:retailer,lat:52,lon,distanceKm:1}};}
const compare=(baskets,costPerKm=0)=>addStoreCombinations({baskets,location:{origin,costPerKm}});
test('combines complementary stores into a complete basket with explicit assignments',()=>{
 const result=compare([basket('A',{rice:100,milk:null}),basket('B',{rice:null,milk:150})]);
 assert.equal(result.baskets[0].complete,true);assert.equal(result.baskets[0].stores.length,2);
 assert.equal(result.baskets[0].totalCents,250);assert.deepEqual(result.baskets[0].lines.map(l=>l.product.retailer),['A','B']);
});
test('travel can make the cheaper product combination more expensive overall',()=>{
 const result=compare([basket('A',{rice:100,milk:200}),basket('B',{rice:200,milk:100},5.05)],1);
 const pair=result.baskets.find(b=>b.stores.length===2);
 assert.equal(pair.totalCents,200);assert.ok(pair.totalWithTravelCents>300);assert.equal(result.baskets[0].stores.length,1);
});
test('equal prices do not manufacture unnecessary extra stops',()=>{
 assert.equal(compare([basket('A',{rice:100,milk:100}),basket('B',{rice:100,milk:100})]).baskets.length,2);
});
test('partial pair never outranks a complete single and preserves unavailable items',()=>{
 const result=compare([basket('A',{rice:100,milk:null,salt:null}),basket('B',{rice:null,milk:100,salt:null}),basket('C',{rice:300,milk:300,salt:300})]);
 assert.ok(result.baskets[0].complete);
 const withoutComplete=compare([basket('A',{rice:100,milk:null,salt:null}),basket('B',{rice:null,milk:100,salt:null})]);
 assert.equal(withoutComplete.baskets[0].missing[0].item.id,'salt');assert.equal(withoutComplete.baskets[0].complete,false);
});

test('pair allocation can recover lines omitted by each individually capped single',async()=>{
 const {summarize}=await import('../src/comparison.js');
 const items=[item('first'),item('second')];
 const candidates=['A','B'].map(retailer=>({product:{retailer,productId:'limited',stableId:'limited',source:{name:'fixture'},
  name:'Rijst',priceCents:100,eligible:true,issues:[],expiresAt:Date.now()+60000,maxPerCustomer:1},decision:{status:'accepted',packages:1,overage:0}}));
 const result=summarize(items,items.map(()=>({candidates})));
 assert.ok(result.baskets.every(b=>b.lines.length===1));
 result.baskets=result.baskets.map(b=>({...b,store:{retailer:b.retailer,name:b.retailer,lat:52,lon:5.01,distanceKm:1},travelCents:0,totalWithTravelCents:b.totalCents}));
 result.location={origin,costPerKm:0};
 const combined=addStoreCombinations(result).baskets[0];
 assert.equal(combined.complete,true);assert.equal(combined.lines.length,2);
 assert.deepEqual(new Set(combined.lines.map(l=>l.product.retailer)),new Set(['A','B']));
 assert.equal(combined.totalCents,200);
});

test('limits 1 through 4 preserve missing lines until four complementary shops are allowed',()=>{
 const baskets=['A','B','C','D'].map((name,i)=>basket(name,Object.fromEntries(['a','b','c','d'].map((id,j)=>[id,i===j?100:null]))));
 for(let maxStores=1;maxStores<=4;maxStores++){
  const result=addStoreCombinations({baskets,location:{origin,costPerKm:0}},{maxStores});
  assert.ok(result.baskets.every(b=>b.stores.length<=maxStores));
  assert.equal(result.baskets[0].missing.length,4-maxStores);
  assert.equal(result.baskets[0].totalCents,maxStores*100);
 }
});
test('invalid store limits are rejected',()=>{
 for(const maxStores of [0,5,2.5,'4'])assert.throws(()=>addStoreCombinations({baskets:[]},{maxStores}));
});
test('four-shop trip finds the shortest round trip regardless of input order',async()=>{
 const {storeRoundTrip}=await import('../src/store-combinations.js');
 const shops=[.04,.01,.03,.02].map(lon=>({lat:52,lon:5+lon}));
 const a=storeRoundTrip(origin,shops),b=storeRoundTrip(origin,[...shops].reverse());
 assert.ok(Math.abs(a.distance-b.distance)<1e-8);
 const {distanceKm}=await import('../src/locations.js');
 assert.ok(Math.abs(a.distance-2*distanceKm(origin,shops[0]))<.001);
});
