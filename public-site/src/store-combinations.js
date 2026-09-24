import {distanceKm} from './locations.js';
import {allocateBasket} from './basket-allocation.js';
const rank=(a,b)=>Number(b.complete)-Number(a.complete)||a.missing.length-b.missing.length||a.totalWithTravelCents-b.totalWithTravelCents||a.stores.length-b.stores.length;
function* subsets(values,size,start=0,prefix=[]){
 if(!size){yield prefix;return;}
 for(let i=start;i<=values.length-size;i++)yield* subsets(values,size-1,i+1,[...prefix,values[i]]);
}
/** Shortest straight-line round trip for at most four selected branches. */
export function storeRoundTrip(origin,stores){
 let best={stores:[],distance:Infinity};
 function visit(remaining,path,last,distance){
  if(!remaining.length){const total=distance+distanceKm(last,origin);if(total<best.distance)best={stores:path,distance:total};return;}
  remaining.forEach((store,i)=>visit(remaining.filter((_,j)=>i!==j),[...path,store],store,distance+distanceKm(last,store)));
 }
 visit(stores,[],origin,0);return best;
}
/** Exhaustive subsets; independent line prices, shared offer caps, nearest branches. */
export function addStoreCombinations(comparison,{maxStores=2}={}) {
 if(!Number.isInteger(maxStores)||maxStores<1||maxStores>4)throw new Error('Kies maximaal 1 tot 4 winkels.');
 const singles=comparison.baskets.map(b=>({...b,stores:[b.store],travelDistanceKm:b.store.distanceKm*2}));
 const items=new Map(),indexed=new Map();
 for(const basket of singles){
  const rows=new Map((basket.choiceRows||[]).map(row=>[row.item.id,row]));
  for(const line of basket.lines){items.set(line.item.id,line.item);if(!rows.has(line.item.id))rows.set(line.item.id,{item:line.item,choices:[line]});}
  for(const missing of basket.missing){items.set(missing.item.id,missing.item);if(!rows.has(missing.item.id))rows.set(missing.item.id,{...missing,choices:[]});}
  indexed.set(basket,rows);
 }
 const bestBySize=new Map(),sourceIssues=[...(comparison.sourceIssues||[])];let evaluated=0;
 for(let size=2;size<=Math.min(maxStores,singles.length);size++)for(const group of subsets(singles,size)){
  evaluated++;
  // Rotate equal-price preferences; smaller subsets already cover fewer stops.
  for(let offset=0;offset<size;offset++){
   const ordered=[...group.slice(offset),...group.slice(0,offset)];
   const rows=[...items.values()].map(item=>({item,choices:ordered.flatMap(b=>indexed.get(b).get(item.id)?.choices||[]),reason:ordered.map(b=>indexed.get(b).get(item.id)?.reason).find(Boolean)||'Geen passend product gevonden.'}));
   const {lines,missing,allocationComplete}=allocateBasket(rows),used=new Set(lines.map(line=>line.product.retailer));
   if(!allocationComplete)sourceIssues.push('Zoeklimiet bij winkelcombinaties bereikt; de goedkoopste verdeling is niet bewezen.');
   if(used.size!==size)continue;
   const tour=storeRoundTrip(comparison.location.origin,group.map(b=>b.store));
   const totalCents=lines.reduce((sum,line)=>sum+line.totalCents,0),travelCents=Math.round(tour.distance*comparison.location.costPerKm*100);
   const basket={retailer:tour.stores.map(s=>s.retailer).join(' + '),stores:tour.stores,lines,missing,allocationComplete,complete:missing.length===0,totalCents,travelCents,totalWithTravelCents:totalCents+travelCents,travelDistanceKm:tour.distance};
   if(!bestBySize.has(size)||rank(basket,bestBySize.get(size))<0)bestBySize.set(size,basket);
  }
 }
 return {...comparison,sourceIssues:[...new Set(sourceIssues)],searchComplete:comparison.searchComplete&&sourceIssues.length===0,baskets:[...singles,...bestBySize.values()].sort(rank),
  combinationCoverage:{maxStores,combinationsEvaluated:evaluated,pairsEvaluated:maxStores>=2?singles.length*(singles.length-1)/2:0,
   assumptions:'Dichtstbijzijnde gekoppelde vestiging per keten; kortste hemelsbrede ronde; regelprijzen afzonderlijk berekend.'}};
}
