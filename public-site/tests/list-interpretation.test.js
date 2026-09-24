import test from 'node:test';
import assert from 'node:assert/strict';
import {interpretList} from '../src/list-interpretation.js';
const amounts=result=>result.rows.map(({query,quantity,unit,kind})=>({query,quantity,unit,kind}));
test('person directive is context, never an item or a product count',()=>{
 assert.deepEqual(amounts(interpretList('Voor 4 personen:\nGehakt\nAardappelen')), [
  {query:'Gehakt',quantity:500,unit:'g',kind:'estimate'},
  {query:'Aardappelen',quantity:1000,unit:'g',kind:'estimate'}]);
 assert.equal(interpretList('gehakt voor 4 personen').rows[0].quantity,500);
 assert.equal(interpretList('4 pers.\ngehakt').rows.length,1);
 assert.equal(interpretList('4p\ngehakt').people,4);
});
test('explicit quantities and multipacks never scale with people',()=>{
 assert.deepEqual(interpretList('Voor 8 personen\n500 g gehakt\n2 x 400 ml kokosmelk\n2 komkommers').rows.map(r=>[r.quantity,r.unit,r.kind]),[[500,'g','explicit'],[800,'ml','explicit'],[2,'stuk','explicit']]);
});
test('fixed groceries and ambiguous products are not multiplied by household size',()=>{
 const names=['tomatenpuree','gehaktkruiden','kokosmelk','sambal','boter','Molokhia','peen en uien','tacos'];
 const rows=interpretList(names.join('\n'),{people:8}).rows;
 assert.deepEqual(rows.map(r=>r.query),names);
 assert.ok(rows.every(r=>r.quantity===1&&r.unit==='verpakking'&&r.kind==='package'));
});
test('alternatives and repeated lines survive review unchanged',()=>{
 const result=interpretList('Taco shells/tortilla’s\nkookroom\nkookroom',{people:8});
 assert.equal(result.rows[0].query,'Taco shells/tortilla’s');
 assert.equal(result.rows[0].quantity,2);
 assert.equal(result.rows.length,3);
 assert.notEqual(result.rows[1].id,result.rows[2].id);
});
test('no person count means no portion assumptions; text count overrides dropdown',()=>{
 assert.equal(interpretList('gehakt').rows[0].kind,'package');
 assert.equal(interpretList('voor 2 personen\ngehakt',{people:6}).rows[0].quantity,250);
});
test('conflicting, fractional and invalid person counts require correction',()=>{
 for(const text of ['voor 0 personen\ngehakt','voor 13 personen\ngehakt','voor 2.5 personen\ngehakt','voor 2 personen\ngehakt voor 4 personen'])assert.throws(()=>interpretList(text));
 assert.throws(()=>interpretList('gehakt',{people:0}));
 assert.throws(()=>interpretList('gehakt\n'.repeat(201),{people:4}));
});
