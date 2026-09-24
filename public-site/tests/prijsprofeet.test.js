import test from 'node:test';
import assert from 'node:assert/strict';
import {normalizeProduct, normalizeSearch, basketPrice} from '../src/prijsprofeet.js';
const now = Date.parse('2026-09-24T12:00:00Z');
const raw = overrides => ({product_id: 'synthetic-1', base_product_id: 'synthetic-base', name: 'Kokosmelk',
  retailer: 'jumbo', price: 1.59, quantity: '400 ml', currency: 'EUR', promotion_status: 'active',
  is_promotional: true, valid_from: '2026-09-21', valid_until: '2026-09-27',
  extracted_at: '2026-09-24T06:00:00Z', ...overrides});
const product = overrides => normalizeProduct(raw(overrides), {now});
test('normalizes current product and prices integer packages', () => {
  const p = product(); assert.equal(p.eligible, true); assert.equal(p.priceCents, 159);
  assert.equal(p.stableId, 'jumbo:synthetic-base');
  assert.deepEqual(basketPrice(p, 3, {now}), {totalCents: 477});
});
test('does not invent a current original price for expired promotion', () => {
  const p = product({promotion_status: 'expired', valid_until: '2026-09-23', original_price: 2.29});
  assert.equal(p.eligible, false); assert.equal(p.priceCents, 159);
  assert.equal(basketPrice(p, 1, {now}).reason, 'expired');
});
test('rejects upcoming, inconsistent dates and unknown status', () => {
  for (const override of [{valid_from:'2026-09-25'}, {valid_until:'2026-02-30'},
    {promotion_status:'surprise'}, {valid_from:'2026-09-27',valid_until:'2026-09-21'}]) {
    assert.equal(product(override).eligible, false);
  }
});
test('regular and optional member prices remain distinct', () => {
  const p = product({loyalty_price:1.19, loyalty_program:'Testkaart'});
  assert.equal(basketPrice(p, 1, {now}).totalCents, 159);
  assert.deepEqual(basketPrice(p, 2, {now, loyalty:true}), {totalCents:238,loyaltyApplied:true});
  for(const loyalty_price of [true,0,-1,'1.19',null])assert.equal(basketPrice(product({loyalty_price,loyalty_program:'Testkaart'}),1,{now,loyalty:true}).totalCents,159);
  assert.equal(basketPrice(product({loyalty_price:1.19}),1,{now,loyalty:true}).totalCents,159);
  assert.equal(basketPrice(product({loyalty_price:1.19,loyalty_program:'Testkaart',multi_buy_quantity:2,multi_buy_price:2.5}),2,{now,loyalty:true}).totalCents,250);
  assert.equal(product({retailer:'albert_heijn'}).eligible, false);
});
test('multibuy, channel and purchase limits affect eligibility', () => {
  const p = product({multi_buy_quantity:2, multi_buy_price:2.5,max_per_customer:4});
  assert.equal(basketPrice(p,4,{now}).totalCents,500);
  assert.equal(basketPrice(p,3,{now}).reason,'multibuy_remainder_unverified');
  assert.equal(basketPrice(p,6,{now}).reason,'purchase_limit');
  assert.equal(basketPrice(product({online_only:true}),1,{now}).reason,'wrong_channel');
  assert.equal(product({multi_buy_quantity:2}).eligible,false);
  for(const promotion_type of ['starting','volume']) assert.ok(product({promotion_type}).issues.includes('complex_promotion'));
});
test('stale, missing, future observation and cache expiry cannot silently quote prices', () => {
  for (const extracted_at of [null,'2026-09-20T12:00:00Z','2026-10-01T12:00:00Z']) {
    assert.equal(product({extracted_at}).eligible,false);
  }
  const p=product();assert.equal(basketPrice(p,1,{now:p.expiresAt}).reason,'stale_price');
});
test('rechecks Dutch calendar validity across midnight even with fresh cache', () => {
  const fetched=Date.parse('2026-09-24T21:50:00Z');
  const p=normalizeProduct(raw({valid_until:'2026-09-24'}),{now:fetched});
  assert.equal(p.eligible,true);
  assert.equal(basketPrice(p,1,{now:Date.parse('2026-09-24T22:01:00Z')}).reason,'expired');
});
test('canonical results schema and pagination are validated, bad records reported', () => {
  const page=normalizeSearch({results:[raw(),{}],total:3,page:1,page_size:2},{now});
  assert.equal(page.hasMore,true);assert.equal(page.products.length,1);assert.equal(page.rejected.length,1);
  assert.throws(()=>normalizeSearch({products:[raw()],total:1,page:1,page_size:1},{now}));
  assert.throws(()=>normalizeSearch({results:[],total:3,page:2,page_size:2},{now,page:2}));
});
test('does not expose images and rejects unsafe product links and bad money', () => {
  const p=product({product_url:'javascript:alert(1)',image_url:'https://example.org/image'});
  assert.equal(p.productUrl,null);assert.equal('image_url' in p,false);
  for (const price of [-1,0,NaN,'1.59',Infinity]) assert.equal(product({price}).eligible,false);
});
