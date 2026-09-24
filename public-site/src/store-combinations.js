import {distanceKm} from './locations.js';
import {allocateBasket} from './basket-allocation.js';
const rank=(a,b)=>Number(b.complete)-Number(a.complete)||a.missing.length-b.missing.length||a.totalWithTravelCents-b.totalWithTravelCents;
/** Exhaustive retailer pairs, with independent line prices and nearest mapped branches.
 * This does not claim optimal road routes, cross-line multibuy allocation or stock.
 */
export function addStoreCombinations(comparison) {
 const singles=comparison.baskets.map(b=>({...b,stores:[b.store],travelDistanceKm:b.store.distanceKm*2}));
 const items=new Map();
 for(const basket of singles){for(const line of basket.lines)items.set(line.item.id,line.item);
  for(const missing of basket.missing)items.set(missing.item.id,missing.item);}
 const pairs=[],sourceIssues=[...(comparison.sourceIssues||[])];
 for(let a=0;a<singles.length;a++)for(let b=a+1;b<singles.length;b++){
  const left=singles[a],right=singles[b];
  const leftLines=new Map(left.lines.map(line=>[line.item.id,line])),rightLines=new Map(right.lines.map(line=>[line.item.id,line]));
  // Two tie preferences avoid introducing a needless second stop for equal prices.
  for(const preferLeft of [true,false]){
   const rows=[];
   for(const item of items.values()){
    const l=leftLines.get(item.id),r=rightLines.get(item.id);
    const lc=left.choiceRows?.find(row=>row.item.id===item.id)?.choices||(l?[l]:[]);
    const rc=right.choiceRows?.find(row=>row.item.id===item.id)?.choices||(r?[r]:[]);
    rows.push({item,choices:preferLeft?[...lc,...rc]:[...rc,...lc],
      reason:left.missing.find(m=>m.item.id===item.id)?.reason||right.missing.find(m=>m.item.id===item.id)?.reason||'Geen passend product gevonden.'});
   }
   const {lines,missing,allocationComplete}=allocateBasket(rows),used=new Set(lines.map(line=>line.product.retailer));
   if(!allocationComplete)sourceIssues.push('Zoeklimiet bij winkelcombinaties bereikt; de goedkoopste verdeling is niet bewezen.');
   if(used.size!==2)continue; // A one-shop allocation is already represented by its single basket.
   const stores=[left.store,right.store].sort((a,b)=>a.distanceKm-b.distanceKm);
   const travelDistanceKm=distanceKm(comparison.location.origin,stores[0])+distanceKm(stores[0],stores[1])+distanceKm(stores[1],comparison.location.origin);
   const totalCents=lines.reduce((sum,line)=>sum+line.totalCents,0),travelCents=Math.round(travelDistanceKm*comparison.location.costPerKm*100);
   pairs.push({retailer:stores.map(s=>s.retailer).join(' + '),stores,lines,missing,allocationComplete,complete:missing.length===0,
    totalCents,travelCents,totalWithTravelCents:totalCents+travelCents,travelDistanceKm});
  }
 }
 pairs.sort(rank);
 const bestPair=pairs[0];
 return {...comparison,sourceIssues:[...new Set(sourceIssues)],searchComplete:comparison.searchComplete&&sourceIssues.length===0,baskets:[...singles,...(bestPair?[bestPair]:[])].sort(rank),
  combinationCoverage:{maxStores:2,pairsEvaluated:singles.length*(singles.length-1)/2,
    assumptions:'Dichtstbijzijnde gekoppelde vestiging per keten; hemelsbrede ronde; regelprijzen afzonderlijk berekend.'}};
}
