import React, {useEffect, useMemo, useState} from 'react';
import {loadAvailableCatalogue} from './checkjebon.js';
const normalize=s=>s.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/[^a-z0-9]+/g,' ').trim();
export function ProductPicker({item,onSelect,onClose}){
 const [query,setQuery]=useState(item.query.replace(/vleeswaren\s*/i,'').replace(/chocopasta/i,'choco').replace(/ongezoete?\s*/i,''));
 const [catalogue,setCatalogue]=useState(null),[error,setError]=useState('');
 useEffect(()=>{let alive=true;const controller=new AbortController();loadAvailableCatalogue({signal:controller.signal}).then(data=>{if(alive){setCatalogue(data);if(data.sourceIssues?.length)setError('Niet alle brongegevens zijn beschikbaar.');}}).catch(e=>{if(alive)setError(e.message);});return()=>{alive=false;controller.abort();};},[]);
 const indexed=useMemo(()=>[...new Map((catalogue?.products||[]).map(p=>[`${p.retailer}:${p.productId}`,{...p,searchName:normalize(p.name)}])).values()],[catalogue]);
 const choices=useMemo(()=>{const terms=normalize(query).split(' ').filter(Boolean);if(!terms.length)return[];return indexed.filter(p=>p.eligible&&terms.every(t=>p.searchName.includes(t))).sort((a,b)=>a.name.localeCompare(b.name,'nl')||a.priceCents-b.priceCents);},[indexed,query]);
 return <div className="product-picker" role="region" aria-label={`Product kiezen voor ${item.query}`}>
  <div className="picker-heading"><strong>Kies een product</strong><button type="button" onClick={onClose} aria-label="Productkeuze sluiten">Sluiten</button></div>
  <label>Zoek op productnaam<input autoFocus value={query} onChange={e=>setQuery(e.target.value)} placeholder="Bijv. kipfilet of chocoladepasta" /></label>
  <p>Zoek in Checkjebon. Controleer de variant voordat je kiest.</p>
  {error&&<p role="status">{error}</p>}
  {!catalogue&&!error&&<p role="status">Producten laden…</p>}
  {catalogue&&<><label>Product<select value="" onChange={e=>{const product=choices[Number(e.target.value)];if(product)onSelect(product);}}><option value="" disabled>{choices.length?'Selecteer een product':'Geen producten gevonden'}</option>{choices.slice(0,100).map((p,i)=><option key={`${p.retailer}:${p.productId}`} value={i}>{p.name} · {p.package||'inhoud onbekend'} · {p.retailer} · € {(p.priceCents/100).toFixed(2).replace('.',',')}</option>)}</select></label><p>{choices.length>100?'Meer dan 100 resultaten. Maak je zoekterm specifieker.':'Kies zelf de juiste variant. Je hoeveelheid blijft behouden. De winkel moet binnen je zoekafstand liggen.'}</p></>}
  {item.selectedProduct&&<button type="button" onClick={()=>onSelect(null)}>Automatisch vergelijken herstellen</button>}
 </div>;
}
