export function safeProductUrl(value){try{const url=new URL(value);return url.protocol==='https:'&&!url.username&&!url.password?url.href:null;}catch{return null;}}
export function shopMapUrl(store){return /^node\/\d+$|^way\/\d+$|^relation\/\d+$/.test(store.id)?`https://www.openstreetmap.org/${store.id}`:null;}
export function shopDirectionsUrl(store){return Number.isFinite(store.lat)&&Number.isFinite(store.lon)?`https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(`${store.lat},${store.lon}`)}`:null;}
