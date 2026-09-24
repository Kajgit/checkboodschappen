/** Exact best-first allocation of independent line prices under shared offer caps.
 * No cross-line discount aggregation. A bounded search reports uncertainty.
 */
const rank=(a,b)=>a.missing-b.missing||a.cost-b.cost;
class Heap {
 values=[];
 push(value){const a=this.values;a.push(value);let i=a.length-1;while(i){const p=(i-1)>>1;if(rank(a[p],value)<=0)break;a[i]=a[p];i=p;}a[i]=value;}
 pop(){const a=this.values,first=a[0],last=a.pop();if(a.length){let i=0;while(i*2+1<a.length){let c=i*2+1;if(c+1<a.length&&rank(a[c+1],a[c])<0)c++;if(rank(last,a[c])<=0)break;a[i]=a[c];i=c;}a[i]=last;}return first;}
}
function violation(lines){
 if(!lines.some(line=>line?.product.maxPerCustomer))return;
 const groups=new Map();
 for(const [index,line] of lines.entries()){
  if(!line)continue;
  const p=line.product,key=JSON.stringify([p.source?.name,p.retailer,p.stableId||p.productId||p.name]);
  const group=groups.get(key)||{count:0,limit:Infinity,indices:[]};
  group.count+=line.decision.packages;group.limit=Math.min(group.limit,p.maxPerCustomer||Infinity);group.indices.push(index);groups.set(key,group);
 }
 return [...groups.values()].find(group=>group.count>group.limit)?.indices;
}
export function allocateBasket(rows,{maxStates=5000}={}){
 const options=rows.map(row=>[...row.choices].sort((a,b)=>a.totalCents-b.totalCents));
 const state=indices=>{const lines=indices.map((index,i)=>options[i][index]||null);return {indices,lines,
  missing:lines.filter(line=>!line).length,cost:lines.reduce((sum,line)=>sum+(line?.totalCents||0),0)};};
 const finish=(result,complete)=>({lines:result.lines.filter(Boolean),missing:result.lines.flatMap((line,i)=>line?[]:[{
  item:rows[i].item,reason:rows[i].choices.length?'Actielimiet geldt voor de hele lijst; geen passende aankoop binnen die limiet geselecteerd.':rows[i].reason}]),
  allocationComplete:complete,states:seen.size});
 const start=state(rows.map(()=>0)),queue=new Heap(),seen=new Set([start.indices.join(',')]);queue.push(start);
 // Guaranteed feasible fallback: move conflicting lines through alternatives.
 let fallback=start;
 while(true){const conflict=violation(fallback.lines);if(!conflict)break;const next=[...fallback.indices];next[conflict.at(-1)]++;fallback=state(next);}
 while(queue.values.length){
  const current=queue.pop(),conflict=violation(current.lines);
  if(!conflict)return finish(current,true);
  // Every valid descendant must change at least one line in this conflict.
  for(const index of conflict){
   const next=[...current.indices];next[index]++;const key=next.join(',');if(seen.has(key))continue;
   if(seen.size>=maxStates)return finish(fallback,false);
   seen.add(key);queue.push(state(next));
  }
 }
 return finish(fallback,true);
}
