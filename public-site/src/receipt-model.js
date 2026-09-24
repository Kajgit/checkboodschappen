const money=n=>new Intl.NumberFormat('nl-NL',{style:'currency',currency:'EUR'}).format(n/100);
const date=n=>Number.isFinite(n)?new Date(n).toLocaleString('nl-NL',{timeZone:'Europe/Amsterdam'}):'onbekend';
export const RECEIPT_SOURCES=[{name:'Checkjebon',url:'https://www.checkjebon.nl/'},{name:'PrijsProfeet',url:'https://www.prijsprofeet.nl/'}];
export function receiptRows(basket,comparison) {
 const rows=[];let activeGroup;
 const add=(text,kind='body',extra={})=>rows.push({text:String(text),kind,...(activeGroup?{group:activeGroup}:{}),...extra});
 const stores=basket.stores||(basket.store?[basket.store]:[]);
 for(const [index,line] of basket.lines.entries()) {
  activeGroup=`product-${index}`;
  add(`${line.product.name} — ${money(line.totalCents)}`,'heading',{label:line.product.name,amount:money(line.totalCents),url:line.product.productUrl});
  add(`${line.decision.packages} × ${line.product.package||'verpakking'} · ${line.product.retailer||''} · ${line.product.source.name}`,'small',{url:line.product.source.url});
  if(line.product.maxPerCustomer)add(`Deze prijs geldt voor maximaal ${line.product.maxPerCustomer} verpakking(en) per klant, over alle regels samen.`,'small');
  if(line.decision.promotionExtraPackages)add(`Actie: ${line.decision.promotionExtraPackages} extra verpakking(en).`,'small');
  if(line.decision.overage>0)add(`Gevraagd ${line.item.quantity} ${line.item.unit} · extra ${Number(line.decision.overage.toFixed(3))} ${{weight:'g',volume:'ml',count:'stuk(s)',package:'verpakking(en)'}[line.decision.dimension]||''}`,'small');
  if(line.product.loyaltyRequired)add(`Ledenprijs: klantenkaart vereist${line.product.loyaltyProgram?` (${line.product.loyaltyProgram})`:''}.`,'warning');
 }
 activeGroup='totals';
 if(!basket.complete||basket.travelCents>0)add(`${basket.complete?'Producten':'Subtotaal'}: ${money(basket.totalCents)}`,'total');
 if(stores.length&&basket.travelCents>0){add(`Reiskostenindicatie: ${money(basket.travelCents)}`,'small');add(`Inclusief reis: ${money(basket.totalWithTravelCents)}`,'total');}
 activeGroup=undefined;
 if(basket.missing.length){add(`GEDEELTELIJK · ${basket.missing.length} ontbrekende regels`,'warning');for(const m of basket.missing){add(`${m.item.query} (${m.item.quantity} ${m.item.unit})`,'body');add(m.reason,'small');}}
 if(stores.length){add('WINKELS','heading');for(const store of stores)add(`${store.name} · ${store.address||''}`,'small',{url:`https://www.openstreetmap.org/${store.id}`});
  if(basket.travelCents>0)add('Reiskosten zijn een indicatie op basis van hemelsbrede afstand.','small');}
 if(!comparison.searchComplete)add('Prijsvergelijking onvolledig: niet alle bronprijzen zijn meegenomen.','warning');
 return rows;
}
export function wrapText(text,maxWidth,measure) {
 const lines=[];let current='';
 for(const word of String(text).split(/\s+/)) {
  if(measure(current?`${current} ${word}`:word)<=maxWidth) {current=current?`${current} ${word}`:word;continue;}
  if(current){lines.push(current);current='';}
  if(measure(word)<=maxWidth){current=word;continue;}
  for(const char of word){if(current&&measure(current+char)>maxWidth){lines.push(current);current='';}current+=char;}
 }
 if(current)lines.push(current);
 return lines.length?lines:[''];
}
/** Rows are never truncated. Page headers/footers are drawn separately. */
export function paginateRows(rows,{width=700,height=930,measure,compact=false}) {
 const pages=[[]];let used=0;
 const layout=rows.map(row=>{
  const size=compact?(row.kind==='total'?24:row.kind==='heading'?18:row.kind==='credit'?11:row.kind==='small'?13:15):(row.kind==='total'?26:row.kind==='heading'?21:row.kind==='small'?15:18);
  const lineHeight=Math.ceil(size*1.4),spacing=['heading','total','warning'].includes(row.kind)?10:3;
  const lines=wrapText(row.label||row.text,width-(row.amount?110:0),text=>measure(text,size,row.kind));
  return {...row,size,lineHeight,spacing,lines,blockHeight:spacing+lines.length*lineHeight};
 });
 for(const [index,row] of layout.entries()) {
  const {size,lineHeight,spacing,lines}=row;
  if(row.group&&layout[index-1]?.group!==row.group){
   let groupHeight=0;
   for(let next=index;next<layout.length&&layout[next].group===row.group;next++)groupHeight+=layout[next].blockHeight;
   if(groupHeight<=height&&used+groupHeight>height&&pages.at(-1).length){pages.push([]);used=0;}
  }
  if(used+spacing+lineHeight*(row.kind==='heading'?2:1)>height&&pages.at(-1).length){pages.push([]);used=0;}
  used+=spacing;
  for(const [lineIndex,text] of lines.entries()){if(used+lineHeight>height){pages.push([]);used=0;}
   pages.at(-1).push({text,kind:row.kind,size,y:used+size,url:row.url,amount:lineIndex===0?row.amount:null});used+=lineHeight;
  }
 }
 return pages;
}
