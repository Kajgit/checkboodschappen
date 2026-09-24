export const CJB_URL='https://www.checkjebon.nl/data/supermarkets.json';
const retailers={ah:'Albert Heijn',albertheijn:'Albert Heijn',jumbo:'Jumbo',plus:'PLUS',aldi:'ALDI',lidl:'Lidl',dirk:'Dirk',
  ekoplaza:'Ekoplaza',hoogvliet:'Hoogvliet',dekamarkt:'DekaMarkt',vomar:'Vomar',spar:'SPAR',coop:'Coop',poiesz:'Poiesz',picnic:'Picnic',lidlviaboodschaapjenl:'Lidl'};
function urlFor(shop,row) {
  try {
    if(typeof row.l!=='string'||!row.l.trim())return null;
    const url=new URL(row.l,shop.u); 
    return url.protocol==='https:'?url.href:null;
  }catch{return null;}
}
export function normalizeCatalogue(data,{now=Date.now(),modified=null}={}) {
  if(!Array.isArray(data)||data.length>100) throw new Error('Ongeldig Checkjebon-bestand.');
  const products=[];let rejected=0;
  const parsed=modified?Date.parse(modified):NaN;
  const observed=Number.isFinite(parsed)?parsed:null;
  const future=observed!==null&&observed>now+300000;
  const sourceIssues=observed===null?['De bestandsdatum van Checkjebon ontbreekt of is ongeldig. De ouderdom van deze prijzen is niet bevestigd.']:
    future?['De bestandsdatum van Checkjebon ligt in de toekomst. Deze prijzen worden niet gebruikt.']:[];
  const expiresAt=future?now:Math.min(now+21600000,observed!==null?observed+86400000:Infinity);
  for(const shop of data) {
    const retailer=retailers[String(shop.c||shop.n||'').toLowerCase().replace(/[^a-z0-9]/g,'')];
    if(!retailer||!Array.isArray(shop.d)) {rejected+=Array.isArray(shop.d)?shop.d.length:1;continue;}
    for(const row of shop.d) {
      if(products.length>=150000) throw new Error('De bron bevat meer producten dan de vergelijker aankan.');
      if(typeof row.n!=='string'||!row.n.trim()||typeof row.p!=='number'||!Number.isFinite(row.p)||row.p<=.01) {rejected++;continue;}
      const id=`cjb:${shop.n}:${row.l||row.n}`;
      const source={name:'Checkjebon',url:'https://www.checkjebon.nl/'};
      const product={source,productId:id,stableId:id,retailer,name:row.n,package:typeof row.s==='string'?row.s:'',
        priceCents:Math.round(row.p*100),fetchedAt:now,observedAt:observed,timestampKind:'catalogue',expiresAt,productUrl:urlFor(shop,row),
        eligible:expiresAt>now,issues:expiresAt>now?[]:['stale_price']};
      // Same exact, source-backed facts as app/product_facts.py; never broad hutspot inference.
      if(shop.n==='ah'&&((row.l==='wi80568/ah-hutspot'&&row.n==='AH Hutspot')||
         (row.l==='wi129681/ah-hutspot-grootverpakking'&&row.n==='AH Hutspot grootverpakking'))) product.category='groente';
      products.push(product);
    }
  }
  return {products,rejected,fetchedAt:now,expiresAt,modified:observed,sourceIssues};
}
let memory=null,pending=null;
export async function loadCatalogue({fetcher=fetch,signal,now=Date.now()}={}) {
  if(memory&&memory.expiresAt>now) return memory;
  if(pending) return pending;
  pending=(async()=>{
    const response=await fetcher(CJB_URL,{signal});
    if(!response.ok) throw new Error('Checkjebon is niet bereikbaar. Probeer het later opnieuw.');
    const raw=await response.json();
    const result=normalizeCatalogue(raw,{now,modified:response.headers.get('Last-Modified')});
    memory=result;return result;
  })();
  try{return await pending;}finally{pending=null;}
}

/** A failed baseline must not prevent another source from being searched. */
export async function loadAvailableCatalogue(options={}) {
  try {return await loadCatalogue(options);}
  catch(error) {
    options.signal?.throwIfAborted();
    return {products:[],rejected:0,fetchedAt:Date.now(),expiresAt:Infinity,modified:null,
      sourceIssues:['Checkjebon is niet beschikbaar. De vergelijking gebruikt alleen resultaten van andere bereikbare bronnen. Probeer later opnieuw.']};
  }
}
