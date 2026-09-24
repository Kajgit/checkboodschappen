import test from 'node:test';
import assert from 'node:assert/strict';
import {receiptRows,paginateRows,wrapText} from '../src/receipt-model.js';
test('partial receipt retains missing rows, price conditions and source warnings',()=>{
 const rows=receiptRows({complete:false,totalCents:300,lines:[{item:{query:'kokosmelk',quantity:800,unit:'ml'},
 product:{name:'Kokosmelk',package:'400 ml',source:{name:'PrijsProfeet'},fetchedAt:0,loyaltyRequired:true,maxPerCustomer:2},
 decision:{packages:2},totalCents:300}],missing:[{item:{query:'molokhia',quantity:1,unit:'verpakking'},reason:'Geen brondata'}]},
 {itemCount:2,createdAt:0,searchComplete:false,sourceIssues:['Prijsvergelijking onvolledig']});
 const text=rows.map(r=>r.text).join('\n');
 for(const expected of ['GEDEELTELIJK','Subtotaal','molokhia','Geen brondata','klantenkaart','Prijsvergelijking onvolledig','PrijsProfeet','maximaal 2 verpakking(en) per klant, over alle regels samen'])assert.ok(text.includes(expected));
});
test('long receipts paginate without truncating any words',()=>{
 const rows=Array.from({length:200},(_,i)=>({text:`Product ${i} met een lange omschrijving en hoeveelheden`,kind:'body'}));
 const pages=paginateRows(rows,{width:150,height:300,measure:(text,size)=>text.length*size/2});
 assert.ok(pages.length>8);
 assert.equal(pages.flat().map(r=>r.text).join(' '),rows.map(r=>r.text).join(' '));
 assert.ok(pages.every(page=>page.every(row=>row.y<=300)));
});
test('unbroken words and non-Latin names wrap without dropping characters',()=>{
 const text='ملوخية'.repeat(30);const lines=wrapText(text,20,s=>s.length);
 assert.equal(lines.join(''),text);assert.ok(lines.every(line=>line.length<=20));
});
test('product and travel totals move together to the next page',()=>{
 const rows=[{text:'Product',kind:'body'},
  {text:'Producttotaal: € 3,00',kind:'total',group:'totals'},
  {text:'Reiskosten: € 1,00',kind:'small',group:'totals'},
  {text:'Totaal: € 4,00',kind:'total',group:'totals'}];
 const pages=paginateRows(rows,{width:700,height:130,measure:text=>text.length*8});
 assert.equal(pages.length,2);
 assert.deepEqual(pages[0].map(row=>row.text),['Product']);
 assert.deepEqual(pages[1].map(row=>row.text),rows.slice(1).map(row=>row.text));
});
test('oversized grouped totals still paginate without losing content or empty pages',()=>{
 const rows=Array.from({length:12},(_,i)=>({text:`Total ${i}`,kind:'total',group:'totals'}));
 const pages=paginateRows(rows,{width:700,height:100,measure:text=>text.length*8});
 assert.ok(pages.every(page=>page.length&&page.every(row=>row.y<=100)));
 assert.deepEqual(pages.flat().map(row=>row.text),rows.map(row=>row.text));
});
test('compact slip retains separate prices and safe-link metadata through wrapping',()=>{
 const rows=[{text:'Long product € 12,50',label:'A very long product name that wraps onto several lines',amount:'€ 12,50',kind:'heading'}, {text:'Product page',kind:'body',url:'https://example.com/item'}];
 const pages=paginateRows(rows,{compact:true,width:220,height:900,measure:(s,n)=>s.length*n/2});
 assert.equal(pages.flat().filter(row=>row.amount).length,1);
 assert.equal(pages.flat().find(row=>row.amount).amount,'€ 12,50');
 assert.equal(pages.flat().at(-1).url,'https://example.com/item');
});
