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

export function basketSummary(basket,itemCount) {
 const missing=basket.missing.length;
 return {
  label:missing?'Subtotaal':'Geschatte productkosten',
  coverage:`${basket.lines.length}/${itemCount} producten geprijsd${missing?` · ${missing} niet meegerekend`:''}`,
  exclusions:'Statiegeld niet apart berekend. Controleer prijs en verpakking in de winkel.',
 };
}
