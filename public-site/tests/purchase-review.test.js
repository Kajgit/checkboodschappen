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
