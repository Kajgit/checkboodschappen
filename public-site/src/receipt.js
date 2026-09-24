import {PDFDocument,PDFName,PDFString} from '../vendor/pdf-lib.js';
import {zipSync} from '../vendor/fflate.js';
import {receiptRows,paginateRows,RECEIPT_SOURCES,wrapText} from './receipt-model.js';
import {safeProductUrl} from './links.js';
const WIDTH=600,MARGIN=38,MAX_BODY=900;
const money=n=>new Intl.NumberFormat('nl-NL',{style:'currency',currency:'EUR'}).format(n/100);
const font=(size,bold=false)=>`${bold?'600':'400'} ${size}px "Public Sans", sans-serif`;
function canvas(height=10){const value=document.createElement('canvas');value.width=WIDTH;value.height=height;return value;}
function sources(comparison){return comparison.location?[...RECEIPT_SOURCES,{name:'© OpenStreetMap · ODbL',url:'https://www.openstreetmap.org/copyright'},{name:'PDOK / BAG',url:'https://www.pdok.nl/'}]:RECEIPT_SOURCES;}
export function renderReceiptPages(basket,comparison,logo=null) {
 const measuring=canvas().getContext('2d');if(!measuring)throw new Error('Afbeeldingen worden niet ondersteund door deze browser.');
 measuring.font=font(19,true);const title=wrapText(basket.retailer,WIDTH-2*MARGIN,t=>measuring.measureText(t).width);
 const TOP=190+title.length*25;
 const pages=paginateRows(receiptRows(basket,comparison),{width:WIDTH-2*MARGIN,height:MAX_BODY,compact:true,
 measure:(text,size,kind)=>{measuring.font=font(size,['heading','total'].includes(kind));return measuring.measureText(text).width;}});
 const heights=pages.map(rows=>TOP+(rows.at(-1)?.y||0)+38+sources(comparison).length*18+65);
 return {length:pages.length,heights,*[Symbol.iterator](){for(const [index,rows] of pages.entries()){
  const height=heights[index],image=canvas(height),ctx=image.getContext('2d');image.receiptLinks=[];
  ctx.fillStyle='#fff';ctx.fillRect(0,0,WIDTH,height);
  if(logo)ctx.drawImage(logo,MARGIN,25,30,30);
  ctx.font=font(15,true);ctx.fillStyle='#1e293b';ctx.fillText('Checkboodschappen',MARGIN+(logo?38:0),47);
  ctx.textAlign='right';ctx.font=font(11);ctx.fillStyle='#64748b';ctx.fillText(`BOODSCHAPPENBON · ${index+1}/${pages.length}`,WIDTH-MARGIN,52);ctx.textAlign='left';
  ctx.font=font(12);ctx.fillText(basket.complete?'BOODSCHAPPEN':'GEDEELTELIJK MANDJE',MARGIN,91);
  ctx.fillStyle='#172337';ctx.font=font(46,true);ctx.fillText(money(basket.totalWithTravelCents??basket.totalCents),MARGIN,143);
  ctx.font=font(19,true);for(const [i,text] of title.entries())ctx.fillText(text,MARGIN,178+i*25);
  ctx.font=font(11);ctx.fillStyle='#64748b';ctx.fillText(`${basket.lines.length}/${comparison.itemCount} producten · ${new Date(comparison.createdAt).toLocaleString('nl-NL',{timeZone:'Europe/Amsterdam'})}`,MARGIN,TOP-15);
  ctx.strokeStyle='#b9c3d1';ctx.setLineDash([4,4]);ctx.beginPath();ctx.moveTo(MARGIN,TOP);ctx.lineTo(WIDTH-MARGIN,TOP);ctx.stroke();ctx.setLineDash([]);
  for(const row of rows){ctx.fillStyle=row.kind==='warning'?'#946020':['small','credit'].includes(row.kind)?'#68758a':'#1e293b';ctx.font=font(row.size,['heading','total'].includes(row.kind));
   ctx.fillText(row.text,MARGIN,TOP+row.y);
   if(row.amount){ctx.textAlign='right';ctx.fillText(row.amount,WIDTH-MARGIN,TOP+row.y);ctx.textAlign='left';}
   const url=safeProductUrl(row.url);if(url)image.receiptLinks.push({url,x:MARGIN,y:TOP+row.y-row.size,width:Math.min(WIDTH-2*MARGIN,ctx.measureText(row.text).width),height:row.size+5});
  }
  const footer=TOP+(rows.at(-1)?.y||0)+30;
  ctx.strokeStyle='#ccd3de';ctx.setLineDash([3,4]);ctx.beginPath();ctx.moveTo(MARGIN,footer);ctx.lineTo(WIDTH-MARGIN,footer);ctx.stroke();ctx.setLineDash([]);
  ctx.font=font(10);ctx.fillStyle='#68758a';ctx.fillText('Indicatieve prijzen · controleer prijs en voorraad in de winkel.',MARGIN,footer+20);
  sources(comparison).forEach((source,i)=>{const y=footer+39+i*18;const label=`${source.name} · ${source.url.replace('https://','').replace(/\/$/,'')}`;ctx.fillText(label,MARGIN,y);image.receiptLinks.push({url:source.url,x:MARGIN,y:y-11,width:WIDTH-2*MARGIN,height:15});});
  // Subtle perforated paper edge, independent of the export format.
  ctx.fillStyle='#edf1f7';for(let x=0;x<WIDTH;x+=16){ctx.beginPath();ctx.moveTo(x,height);ctx.lineTo(x+8,height-6);ctx.lineTo(x+16,height);ctx.fill();}
  yield image;
 }}};
}
let logoPromise;
function loadLogo(){return logoPromise??=new Promise(resolve=>{const img=new Image();img.onload=()=>resolve(img);img.onerror=()=>{logoPromise=null;resolve(null);};img.src='/favicon.png';});}
const blobOf=canvas=>new Promise((resolve,reject)=>canvas.toBlob(blob=>blob?resolve(blob):reject(new Error('Afbeelding kon niet worden gemaakt.')),'image/png'));
export async function createReceipt(basket,comparison,format) {
 await document.fonts?.load('400 15px "Public Sans"');await document.fonts?.load('600 18px "Public Sans"');
 const logo=await loadLogo();
 const pages=renderReceiptPages(basket,comparison,logo),name=`boodschappenbon-${basket.retailer.toLowerCase().replace(/[^a-z0-9]+/g,'-')}`;
 if(format==='pdf') {
  const pdf=await PDFDocument.create();pdf.setTitle(`Boodschappenbon ${basket.retailer}`);pdf.setCreator('Checkboodschappen');pdf.setSubject('Indicatieve boodschappenprijzen');
  for(const canvas of pages){const image=await pdf.embedPng(await (await blobOf(canvas)).arrayBuffer()),scale=.5,h=canvas.height*scale,page=pdf.addPage([WIDTH*scale,h]);page.drawImage(image,{x:0,y:0,width:WIDTH*scale,height:h});
   const links=canvas.receiptLinks.map(link=>pdf.context.register(pdf.context.obj({Type:'Annot',Subtype:'Link',Rect:[link.x*scale,h-(link.y+link.height)*scale,(link.x+link.width)*scale,h-link.y*scale],Border:[0,0,0],A:{Type:'Action',S:'URI',URI:PDFString.of(link.url)}})));
   page.node.set(PDFName.of('Annots'),pdf.context.obj(links));
  }
  return {blob:new Blob([await pdf.save()],{type:'application/pdf'}),filename:`${name}.pdf`,pages:pages.length};
 }
 if(format!=='png')throw new Error('Onbekend exportformaat.');
 if(pages.length<=8){const tall=canvas(pages.heights.reduce((a,b)=>a+b,0)),ctx=tall.getContext('2d');let y=0;for(const page of pages){ctx.drawImage(page,0,y);y+=page.height;}return {blob:await blobOf(tall),filename:`${name}.png`,pages:pages.length};}
 const files={};let i=0;for(const page of pages)files[`${name}-${String(++i).padStart(2,'0')}.png`]=new Uint8Array(await (await blobOf(page)).arrayBuffer());
 return {blob:new Blob([zipSync(files,{level:0})],{type:'application/zip'}),filename:`${name}-png-paginas.zip`,pages:pages.length};
}
export async function downloadReceipt(basket,comparison,format){const result=await createReceipt(basket,comparison,format),url=URL.createObjectURL(result.blob),a=document.createElement('a');a.href=url;a.download=result.filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),30000);return result;}
