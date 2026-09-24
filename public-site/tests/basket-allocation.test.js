import test from 'node:test';
import assert from 'node:assert/strict';
import {allocateBasket} from '../src/basket-allocation.js';
const line=(id,offer,cost,packs=1,limit=1)=>({item:{id},product:{productId:offer,stableId:offer,retailer:'A',source:{name:'fixture'},maxPerCustomer:limit},decision:{packages:packs},totalCents:cost});
const row=(id,choices)=>({item:{id},choices,reason:'Unavailable'});
test('allocates a shared limited offer to the line without alternatives',()=>{
 const rows=[row('flex',[line('flex','limited',100),line('flex','alternative',200)]),row('only',[line('only','limited',100)])];
 const result=allocateBasket(rows);
 assert.equal(result.allocationComplete,true);assert.equal(result.missing.length,0);
 assert.deepEqual(result.lines.map(l=>l.product.productId),['alternative','limited']);
 assert.equal(result.lines.reduce((s,l)=>s+l.totalCents,0),300);
});
test('counts packages across lines, not the number of matching lines',()=>{
 const result=allocateBasket([row('a',[line('a','offer',200,2,3)]),row('b',[line('b','offer',200,2,3)])]);
 assert.equal(result.lines.length,1);assert.equal(result.missing.length,1);assert.equal(result.allocationComplete,true);
});
test('bounded search only returns feasible results and discloses incomplete optimization',()=>{
 const result=allocateBasket([row('a',[line('a','offer',100),line('a','other',200)]),row('b',[line('b','offer',100)])],{maxStates:1});
 assert.equal(result.allocationComplete,false);
 assert.ok(result.lines.filter(l=>l.product.productId==='offer').length<=1);
});
test('small constrained cases agree with independent exhaustive enumeration',()=>{
 for(let seed=1;seed<=30;seed++){
  const rows=Array.from({length:4},(_,i)=>row(String(i),[
   line(String(i),'shared',(seed*(i+3)%7+1)*10,(i+seed)%2+1,3),
   line(String(i),`own-${i}`,(seed*(i+7)%11+1)*10,1,1)]));
  let best=[Infinity,Infinity];
  for(let n=0;n<81;n++){
   let value=n,cost=0,missing=0,used=0;
   for(const r of rows){const option=value%3;value=Math.floor(value/3);const l=r.choices[option];if(!l){missing++;continue;}cost+=l.totalCents;if(l.product.productId==='shared')used+=l.decision.packages;}
   if(used<=3&&(missing<best[0]||missing===best[0]&&cost<best[1]))best=[missing,cost];
  }
  const result=allocateBasket(rows);
  assert.equal(result.allocationComplete,true);
  assert.deepEqual([result.missing.length,result.lines.reduce((s,l)=>s+l.totalCents,0)],best);
 }
});
