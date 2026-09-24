import test from 'node:test';
import assert from 'node:assert/strict';
import {parseList} from '../src/list-input.js';
const parsed=text=>parseList(text,{id:()=> 'test'}).map(({id,...item})=>item);
test('pasted list keeps unspecified amounts as packages and preserves alternatives',()=>{
  assert.deepEqual(parsed('•\u2060 Kokosmelk\n• Taco shells/tortilla’s'),[
    {query:'Kokosmelk',quantity:1,unit:'verpakking'},
    {query:'Taco shells/tortilla’s',quantity:1,unit:'verpakking'}]);
});
test('explicit units, decimal commas and multipacks preserve requested amounts',()=>{
  assert.deepEqual(parsed('2 x 400 ml kokosmelk\ngehakt 0,75 kg\n2 komkommers\n3 pakken rijst'),[
    {query:'kokosmelk',quantity:800,unit:'ml'}, {query:'gehakt',quantity:.75,unit:'kg'},
    {query:'komkommers',quantity:2,unit:'stuk'},{query:'rijst',quantity:3,unit:'verpakking'}]);
});
test('does not split peen en uien or silently merge duplicates',()=>{
  const items=parsed('peen en uien\nkookroom\nkookroom');assert.equal(items.length,3);
  assert.equal(items[0].query,'peen en uien');
});
test('zero and oversized amounts cannot become valid shopping requests',()=>{
  assert.throws(()=>parsed('0 kg gehakt'));
  assert.throws(()=>parsed('-2 kg gehakt'));
  assert.throws(()=>parsed('999999 kg gehakt'));
  assert.throws(()=>parsed('rijst\n'.repeat(201)));
});
