import {basketPrice} from './prijsprofeet.js';
import {allocateBasket} from './basket-allocation.js';
export function summarize(items,matched,{now=Date.now(),loyalty=false,sourceIssues=[]}={}) {
  const retailerNames=new Set();
  for(const result of matched) for(const candidate of result.candidates) retailerNames.add(candidate.product.retailer);
  const baskets=[];sourceIssues=[...sourceIssues];
  for(const retailer of retailerNames) {
    const rows=[];
    for(let i=0;i<items.length;i++) {
      const item=items[i],choices=[],reasons=[];
      for(const {product,decision} of matched[i].candidates.filter(c=>c.product.retailer===retailer)) {
        if(decision.status!=='accepted') {reasons.push(decision.reason);continue;}
        // A complete offer group can satisfy a smaller requested amount by
        // buying extra packs. Never invent an undiscounted remainder price.
        const group=product.multiBuy?.quantity||1;
        const packages=Math.ceil(decision.packages/group)*group;
        const price=basketPrice(product,packages,{now,loyalty});
        if(price.reason) {reasons.push(price.reason);continue;}
        const extra=packages-decision.packages;
        const purchaseDecision=extra?{...decision,packages,promotionExtraPackages:extra,
          overage:Number.isFinite(decision.packageAmount)?(decision.overage||0)+extra*decision.packageAmount:decision.overage}:decision;
        const selectedProduct=price.loyaltyApplied?{...product,priceCents:product.loyaltyPriceCents,loyaltyRequired:true}:product;
        choices.push({item,product:selectedProduct,decision:purchaseDecision,totalCents:price.totalCents});
      }
      choices.sort((a,b)=>a.totalCents-b.totalCents||(a.decision.overage??Infinity)-(b.decision.overage??Infinity));
      rows.push({item,choices,reason:reasons[0]||matched[i].reason||'Geen passend product gevonden in de geraadpleegde bronnen.'});
    }
    const {lines,missing,allocationComplete}=allocateBasket(rows);
    if(!allocationComplete)sourceIssues.push(`${retailer}: de zoeklimiet voor gezamenlijke actielimieten is bereikt. De geselecteerde aankoop voldoet aan de limieten, maar de goedkoopste verdeling is niet bewezen.`);
    baskets.push({retailer,lines,missing,choiceRows:rows,allocationComplete,complete:missing.length===0,totalCents:lines.reduce((sum,line)=>sum+line.totalCents,0)});
  }
  // Completeness always precedes price. A cheap partial basket cannot win.
  baskets.sort((a,b)=>Number(b.complete)-Number(a.complete)||a.missing.length-b.missing.length||a.totalCents-b.totalCents);
  return {baskets,sourceIssues,searchComplete:sourceIssues.length===0,createdAt:now,itemCount:items.length};
}
const sourceMessages={source_not_enabled:'PrijsProfeet is nog niet ingeschakeld.',provider_busy:'PrijsProfeet is druk; niet alle zoekopdrachten zijn uitgevoerd.',
  provider_rate_limited:'PrijsProfeet beperkt tijdelijk het aantal verzoeken.',visitor_budget_exhausted:'Je hebt de tijdelijke zoeklimiet bereikt.',
  daily_budget_exhausted:'Het gratis dagbudget is bereikt.',provider_cooldown:'PrijsProfeet vraagt ons even te wachten.',
  invalid_query:'Deze zoekterm wordt niet ondersteund door PrijsProfeet.',
  invalid_provider_response:'PrijsProfeet stuurde een onbruikbaar antwoord.',
  service_unavailable:'Onze zoekdienst is tijdelijk niet beschikbaar.',
  server_not_configured:'Onze zoekdienst is niet volledig ingesteld.',
  provider_response_too_large:'Het antwoord van PrijsProfeet is te groot om te verwerken.'};
function sourceError(code,retryHeader=null) {
  let seconds=Number(retryHeader);
  if(retryHeader!==null&&!Number.isFinite(seconds))seconds=(Date.parse(retryHeader)-Date.now())/1000;
  const retryAfterSeconds=Number.isFinite(seconds)&&seconds>0?Math.ceil(seconds):0;
  const advice=retryAfterSeconds?` Probeer over ${Math.ceil(retryAfterSeconds/60)} minuten opnieuw via “Vergelijk boodschappen”.`:
    code==='source_not_enabled'?'':' Probeer later opnieuw via “Vergelijk boodschappen”.';
  return Object.assign(new Error((sourceMessages[code]||'PrijsProfeet is niet bereikbaar.')+advice),{code,retryAfterSeconds});
}
export async function searchPrijsProfeet(query,{signal,fetcher=fetch}={}) {
  let response;
  try {response=await fetcher('/api/search',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query}),signal});}
  catch(error){if(signal?.aborted)throw error;throw sourceError('provider_unavailable');}
  let result;try{result=await response.json();}catch{throw sourceError('provider_unavailable',response.headers.get('retry-after'));}
  if(!response.ok) throw sourceError(result?.error||'provider_unavailable',response.headers.get('retry-after'));
  if(!Array.isArray(result?.products)||typeof result.complete!=='boolean') throw sourceError('invalid_provider_response');
  return result;
}
export async function runComparison(items,catalogue,matcher,{signal,onProgress=()=>{},search=searchPrijsProfeet,loyalty=false,finalize=summarize}={}) {
  if(!items.length) throw new Error('Voeg eerst producten toe.');
  await matcher.request('load',{products:catalogue.products});
  const matched=[],sourceIssues=[...(catalogue.sourceIssues||[])],queries=new Map();let unavailable=null;
  if(catalogue.expiresAt<=Date.now()) sourceIssues.push('Checkjebon bevat verouderde prijzen.');
  if(catalogue.rejected) sourceIssues.push(`${catalogue.rejected} artikelen uit het Checkjebon-prijsbestand zijn overgeslagen omdat de gegevens niet bruikbaar zijn. Dit zijn geen ontbrekende producten uit jouw lijst.`);
  for(let i=0;i<items.length;i++) {
    signal?.throwIfAborted();const item=items[i];onProgress({done:i,total:items.length,query:item.query});
    const extra=[];
    for(const alternative of (item.selectedProduct?.name||item.query).split(/\s*\/\s*|\s+of\s+/i).filter(Boolean)) {
      const query=alternative.trim().toLowerCase();
      if(!queries.has(query)&&!unavailable) {
        try {const result=await search(query,{signal});queries.set(query,result);
          if(!result.complete) sourceIssues.push(`PrijsProfeet: zoekresultaten voor “${alternative}” zijn onvolledig.`);
        }catch(error){if(signal?.aborted)throw error;sourceIssues.push(error.message);queries.set(query,{products:[]});
          if(['source_not_enabled','daily_budget_exhausted','visitor_budget_exhausted','provider_cooldown',
            'provider_busy','provider_rate_limited','provider_unavailable','invalid_provider_response',
            'server_not_configured','service_unavailable','visitor_unavailable'].includes(error.code)) unavailable=error.message;}
      }
      extra.push(...(queries.get(query)?.products||[]));
    }
    const unique=[...new Map(extra.map(p=>[`${p.retailer}:${p.productId}`,p])).values()];
    matched.push(await matcher.request('match',{item,extra:unique}));
  }
  onProgress({done:items.length,total:items.length});
  return finalize(items,matched,{loyalty,sourceIssues:[...new Set(sourceIssues)]});
}
