import test from 'node:test';
import assert from 'node:assert/strict';
import {normalizePostcode,parsePostcodeResponse,distanceKm,nearbyStores,validateStores,applyLocations} from '../src/locations.js';
const origin={lat:52.37,lon:4.89};
const stores=[{id:'1',retailer:'A',name:'A',lat:52.371,lon:4.89},{id:'2',retailer:'A',name:'A2',lat:52.39,lon:4.89},
 {id:'3',retailer:'B',name:'B',lat:51.5,lon:5}];
test('postcode parsing rejects fuzzy results, injection and impossible coordinates',()=>{
 assert.equal(normalizePostcode('1012 js'),'1012JS');assert.throws(()=>normalizePostcode('* OR *'));
 const doc={postcode:'1012JS',bron:'BAG',centroide_ll:'POINT(4.89410619 52.37291108)'};
 assert.equal(parsePostcodeResponse({response:{docs:[doc]}},'1012JS').lon,4.89410619);
 assert.throws(()=>parsePostcodeResponse({response:{docs:[doc]}},'1013JS'));
 assert.throws(()=>parsePostcodeResponse({response:{docs:[{...doc,centroide_ll:'POINT(0 0)'}]}},'1012JS'));
});
test('uses nearest mapped branch per chain and respects radius',()=>{
 assert.equal(distanceKm(origin,origin),0);assert.ok(Math.abs(distanceKm(origin,stores[0])-.1112)<.001);
 const found=nearbyStores(origin,stores,5);assert.equal(found.size,1);assert.equal(found.get('A').id,'1');
});
test('stale or invalid location data cannot masquerade as current',()=>{
 const data={version:1,license:'ODbL-1.0',sourceDate:new Date().toISOString(),stores};
 assert.equal(validateStores(data).stale,false);
 assert.throws(()=>validateStores({...data,sourceDate:'2020-01-01'}));
 assert.throws(()=>validateStores({...data,license:'unknown'}));
});
test('location filter removes distant retailers and separates estimated travel from product cost',()=>{
 const basket=retailer=>({retailer,complete:true,missing:[],totalCents:1000});
 const result=applyLocations({baskets:[basket('A'),basket('B')]},origin,{stores,sourceDate:'2026-09-24'},{radius:5,costPerKm:1});
 assert.equal(result.baskets.length,1);assert.equal(result.baskets[0].totalCents,1000);
 assert.equal(result.baskets[0].travelCents,22);assert.deepEqual(result.excludedRetailers,['B']);
 assert.match(result.location.distanceMethod,/geen rijroute/);
});
