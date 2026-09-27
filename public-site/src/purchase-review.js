// Ask before optimizing choices that materially change what ends up in the basket.
const clean=s=>s.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g,'').trim();
export function purchaseReview(item) {
 if(item.selectedProduct||!item.unit)return null;
 const q=clean(item.query);
 let variants=[];
 if(/^fanta(?: zero)?$/.test(q)) variants=q.endsWith('zero')?['Fanta orange zero','Fanta cassis zero','Fanta lemon zero']:['Fanta orange','Fanta orange zero','Fanta cassis','Fanta lemon'];
 if(/^(?:houdbare? )?melk$/.test(q))variants=(q.includes('houdbaar')?['Houdbare halfvolle melk','Houdbare volle melk','Houdbare magere melk']:['Halfvolle melk','Volle melk','Magere melk']);
 if(q==='sambal')variants=['Sambal oelek','Sambal badjak','Sambal manis'];
 if(/^(?:ice[ -]?tea|iced tea|ijsthee)(?: zero)?$/.test(q))variants=q.endsWith('zero')?['IJsthee perzik zero','IJsthee citroen zero','IJsthee green zero']:['IJsthee perzik','IJsthee citroen','IJsthee green','IJsthee perzik zero','IJsthee citroen zero'];
 const volume=/\b(?:melk|kokosmelk|olijfolie|zonnebloemolie|fanta|ijsthee|ice[ -]?tea|iced tea|frisdrank|kookroom)\b/.test(q);
 const weight=/\b(?:gehakt|rundergehakt|kipfilet|kipdijfilet|shoarma|shoarmavlees|kaas|pindakaas|chocopasta|aardappelen|aardappel)\b/.test(q);
 const amount=(volume||weight)&&['verpakking','stuk'].includes(item.unit);
 if(!variants.length&&!amount)return null;
 return {variants,amount,unit:volume?'ml':'g',reason:variants.length?'Kies een variant of een exact product.':'Vul gram of ml in, of kies een exact product.'};
}

// Compare package contents across the whole candidate set, before allocating stores.
// A cheap 150 g pack cannot silently stand in for a 1 kg pack requested elsewhere.
export function packageReview(item,candidates,{now=Date.now()}={}) {
 if(item.selectedProduct||item.unit!=='verpakking')return null;
 const sizes=new Map();let unknown=false,found=false;
 for(const {product,decision} of candidates) {
  if(decision.status!=='accepted'||!product.eligible||product.expiresAt<=now)continue;
  found=true;
  const unit={weight:'g',volume:'ml',count:'stuk'}[decision.contentsDimension],amount=decision.contentsAmount;
  if(!unit||!Number.isFinite(amount)||amount<=0){unknown=true;continue;}
  sizes.set(`${unit}:${amount}`,{quantity:amount*item.quantity,unit,packAmount:amount});
 }
 if(!found||(!unknown&&sizes.size===1))return null;
 const options=[...sizes.values()].sort((a,b)=>a.unit.localeCompare(b.unit)||a.quantity-b.quantity);
 return {variants:[],amount:true,unit:options[0]?.unit||'g',units:[...new Set(options.map(o=>o.unit).concat(unknown?['g','ml','stuk']:[]))],sizes:options,
  reason:unknown?'Verpakkingsinhoud ontbreekt. Kies de totale hoeveelheid of een exact product.':'Verschillende verpakkingsgroottes gevonden. Kies de totale hoeveelheid.'};
}

export function withQuantity(item,quantity,unit) {
 const {selectedProduct,...rest}=item;
 return {...rest,quantity,unit};
}

export function basketSummary(basket,itemCount) {
 const missing=basket.missing.length;
 return {
  label:missing?'Subtotaal':'Geschatte productkosten',
  coverage:`${basket.lines.length}/${itemCount} producten geprijsd${missing?` · ${missing} niet meegerekend`:''}`,
  exclusions:'Statiegeld niet apart berekend. Controleer prijs en verpakking in de winkel.',
 };
}
