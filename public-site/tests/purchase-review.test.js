import test from 'node:test';
import assert from 'node:assert/strict';
import {purchaseReview,basketSummary} from '../src/purchase-review.js';
import {summarize} from '../src/comparison.js';
const item=(query,unit='verpakking')=>({id:'1',query,unit,quantity:1});
test('generic drinks require variant and real amount, including old saved package requests',()=>{
 for(const q of ['Fanta','houdbare melk','ice tea','ijsthee']){
  const review=purchaseReview(item(q));assert.ok(review.variants.length);assert.equal(review.amount,true);
 }
 assert.ok(purchaseReview(item('Fanta','ml')).variants.length);
 assert.equal(purchaseReview(item('Fanta orange','ml')),null);
 assert.equal(purchaseReview(item('Houdbare volle melk','l')),null);
 assert.equal(purchaseReview(item('IJsthee perzik','l')),null);
});
test('variable pack sizes require an amount or an exact selected product',()=>{
 for(const q of ['Gehakt','Geraspte kaas','Olijfolie','Pindakaas','Kokosmelk'])assert.equal(purchaseReview(item(q)).amount,true);
 assert.equal(purchaseReview(item('Gehakt','g')),null);
 assert.equal(purchaseReview({...item('Fanta'),selectedProduct:{productId:'1',name:'Fanta Cassis',retailer:'AH'}}),null);
 for(const q of ['Gehaktkruiden','Kaascrackers','Komkommer'])assert.equal(purchaseReview(item(q)),null);
});
test('unreviewed choices cannot silently contribute to totals even when matcher accepts them',()=>{
 const i=item('Fanta');const candidate={product:{name:'Fanta Cassis',retailer:'AH',priceCents:85,eligible:true,expiresAt:Date.now()+60000},decision:{status:'accepted',packages:1}};
 const basket=summarize([i],[{candidates:[candidate]}]).baskets[0];
 assert.equal(basket.totalCents,0);assert.equal(basket.complete,false);assert.match(basket.missing[0].reason,/variant/);
 const resolved={...i,query:'Fanta orange',unit:'ml',quantity:500};
 const priced=summarize([resolved],[{candidates:[{...candidate,product:{...candidate.product,name:'Fanta Orange'}}]}]).baskets[0];
 assert.equal(priced.complete,true);
});
test('receipt and app use explicit partial totals and do not promise deposit-inclusive checkout prices',()=>{
 const partial=basketSummary({lines:[{}],missing:[{}]},2);
 assert.equal(partial.label,'Subtotaal');assert.match(partial.coverage,/1\/2.*1 niet meegerekend/);assert.match(partial.exclusions,/Statiegeld/);
 assert.equal(basketSummary({lines:[{}],missing:[]},1).label,'Geschatte productkosten');
});

const pack=(retailer,amount,dimension='weight',price=100)=>({product:{retailer,name:'Rijst',eligible:true,priceCents:price,expiresAt:Date.now()+60000},
 decision:{status:'accepted',packages:1,contentsAmount:amount,contentsDimension:dimension}});
test('package ambiguity is detected across stores, even when each store offers only one size',()=>{
 const i=item('rijst');
 const result=summarize([i],[{candidates:[pack('Lidl',150),pack('Dirk',1000)]}]);
 assert.equal(result.reviews.length,1);
 assert.deepEqual(result.reviews[0].review.sizes.map(s=>s.packAmount),[150,1000]);
 assert.ok(result.baskets.every(b=>b.lines.length===0&&b.missing.length===1));
});
test('same pack sizes are comparable while missing contents need a choice',()=>{
 const i=item('rijst');
 assert.equal(summarize([i],[{candidates:[pack('A',500),pack('B',500)]}]).reviews.length,0);
 for(const candidates of [[pack('A',null)],[pack('A',500),pack('B',null)]]){
  const result=summarize([i],[{candidates}]);assert.equal(result.reviews.length,1);assert.ok(result.baskets.every(b=>!b.lines.length));
 }
 // Rejected and expired records must not create a spurious size conflict.
 const stale=pack('B',1000);stale.product.expiresAt=1;
 const rejected=pack('C',2000);rejected.decision.status='unreviewed';
 assert.equal(summarize([i],[{candidates:[pack('A',500),stale,rejected]}]).reviews.length,0);
});
test('pack counts become total physical amounts and remain portable between stores after saving',async()=>{
 const {withQuantity}=await import('../src/purchase-review.js');
 const {ListStore}=await import('../src/list-store.js');const {IDBFactory}=await import('fake-indexeddb');
 const i={...item('rijst'),quantity:2};
 const review=summarize([i],[{candidates:[pack('A',250),pack('B',1000)]}]).reviews[0].review;
 assert.deepEqual(review.sizes.map(s=>s.quantity),[500,2000]);
 const selected={...i,selectedProduct:{productId:'a',retailer:'A',name:'Rijst'}};
 const resolved=withQuantity(selected,2000,'g');assert.equal(resolved.selectedProduct,undefined);
 const store=new ListStore({indexedDB:new IDBFactory()});await store.save({version:1,postcode:'',items:[resolved]});store.close();
 const saved=(await store.load()).items[0];assert.deepEqual(saved,resolved);store.close();
 const result=summarize([saved],[{candidates:[{...pack('A',250),decision:{...pack('A',250).decision,packages:8}},{...pack('B',1000),decision:{...pack('B',1000).decision,packages:2}}]}]);
 assert.equal(result.reviews.length,0);assert.equal(result.baskets[0].retailer,'B');assert.equal(result.baskets[0].totalCents,200);
});
test('explicit selected pack remains available even when its size is missing',()=>{
 const i={...item('rijst'),selectedProduct:{retailer:'A',productId:'exact',name:'Rijst'}};
 const result=summarize([i],[{candidates:[pack('A',null)]}]);
 assert.equal(result.reviews.length,0);assert.equal(result.baskets[0].lines.length,1);
});
