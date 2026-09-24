export const PDOK_URL='https://api.pdok.nl/bzk/locatieserver/search/v3_1/free';
export function normalizePostcode(value) {
 const postcode=String(value||'').replace(/\s/g,'').toUpperCase();
 if(!/^[1-9]\d{3}[A-Z]{2}$/.test(postcode))throw new Error('Vul een Nederlandse postcode in, bijvoorbeeld 1012 JS.');
 return postcode;
}
export function parsePostcodeResponse(data,postcode) {
 const documents=data?.response?.docs;
 const match=Array.isArray(documents)?documents.find(doc=>doc.postcode===postcode&&doc.bron==='BAG'):null;
 const point=match?.centroide_ll?.match(/^POINT\(\s*([\d.-]+)\s+([\d.-]+)\s*\)$/);
 if(!point)throw new Error('Deze postcode is niet gevonden. Controleer de postcode.');
 const lon=Number(point[1]),lat=Number(point[2]);
 if(!Number.isFinite(lat)||!Number.isFinite(lon)||lat<50.5||lat>53.8||lon<3||lon>7.3)throw new Error('De postcodebron gaf een ongeldige locatie.');
 return {postcode,lat,lon,label:match.weergavenaam||postcode,source:'PDOK / BAG',sourceUrl:'https://www.pdok.nl/'};
}
const postcodes=new Map();
export async function locatePostcode(value,{signal,fetcher=fetch}={}) {
 const postcode=normalizePostcode(value),cached=postcodes.get(postcode);
 if(cached&&Date.now()-cached.fetchedAt<86400000)return cached;
 const url=new URL(PDOK_URL);url.search=new URLSearchParams({q:postcode,fq:'type:postcode',rows:'1',fl:'postcode,centroide_ll,weergavenaam,bron'}).toString();
 const response=await fetcher(url,{signal});if(!response.ok)throw new Error('Postcode zoeken is tijdelijk niet beschikbaar. Probeer het later opnieuw.');
 const result={...parsePostcodeResponse(await response.json(),postcode),fetchedAt:Date.now()};
 if(postcodes.size>=20)postcodes.delete(postcodes.keys().next().value);
 postcodes.set(postcode,result);return result;
}
export function distanceKm(a,b) {
 const rad=value=>value*Math.PI/180,dLat=rad(b.lat-a.lat),dLon=rad(b.lon-a.lon);
 const value=Math.sin(dLat/2)**2+Math.cos(rad(a.lat))*Math.cos(rad(b.lat))*Math.sin(dLon/2)**2;
 return 6371*2*Math.atan2(Math.sqrt(Math.max(0,Math.min(1,value))),Math.sqrt(Math.max(0,1-value)));
}
export function validateStores(data,{now=Date.now()}={}) {
 const date=Date.parse(data?.sourceDate);
 if(data?.version!==1||data.license!=='ODbL-1.0'||!Array.isArray(data.stores)||data.stores.length>30000||!Number.isFinite(date)||date>now+86400000)
  throw new Error('Het winkelbestand is ongeldig.');
 if(now-date>90*86400000)throw new Error('Het winkelbestand is te oud. De beheerder moet de locaties bijwerken.');
 for(const store of data.stores)if(typeof store.id!=='string'||typeof store.retailer!=='string'||typeof store.name!=='string'||
  !Number.isFinite(store.lat)||!Number.isFinite(store.lon)||store.lat<50.5||store.lat>53.8||store.lon<3||store.lon>7.3)
  throw new Error('Een winkel heeft ongeldige locatiegegevens.');
 return {...data,stale:now-date>30*86400000};
}
export function nearbyStores(origin,stores,radius=10) {
 if(!Number.isFinite(radius)||radius<1||radius>50)throw new Error('Kies een zoekafstand van 1 tot 50 km.');
 const found=new Map();
 for(const store of stores){const km=distanceKm(origin,store);if(km>radius)continue;
  const prior=found.get(store.retailer);if(!prior||km<prior.distanceKm)found.set(store.retailer,{...store,distanceKm:km});}
 return found;
}
export function applyLocations(result,origin,dataset,{radius=10,costPerKm=0}={}) {
 if(!Number.isFinite(costPerKm)||costPerKm<0||costPerKm>5)throw new Error('Vul reiskosten in tussen € 0 en € 5 per km.');
 const nearest=nearbyStores(origin,dataset.stores,radius);
 const baskets=result.baskets.filter(b=>nearest.has(b.retailer)).map(basket=>{
  const store=nearest.get(basket.retailer),travelCents=Math.round(store.distanceKm*2*costPerKm*100);
  return {...basket,store,travelCents,totalWithTravelCents:basket.totalCents+travelCents};
 });
 baskets.sort((a,b)=>Number(b.complete)-Number(a.complete)||a.missing.length-b.missing.length||a.totalWithTravelCents-b.totalWithTravelCents);
 return {...result,baskets,location:{origin,radius,costPerKm,sourceDate:dataset.sourceDate,stale:dataset.stale,
  distanceMethod:'hemelsbreed vanaf het postcodecentrum; geen rijroute',storeSource:'OpenStreetMap contributors',storeLicense:'ODbL-1.0'},
  excludedRetailers:result.baskets.filter(b=>!nearest.has(b.retailer)).map(b=>b.retailer)};
}
