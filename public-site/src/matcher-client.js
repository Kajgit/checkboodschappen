export class MatcherClient {
  constructor() {
    this.worker=new Worker(new URL('./matcher-worker.js',import.meta.url),{type:'module'});
    this.pending=new Map();this.sequence=0;this.closedError=null;
    this.worker.onmessage=({data})=>{const job=this.pending.get(data.id);if(!job)return;
      this.pending.delete(data.id);clearTimeout(job.timeout);data.error?job.reject(new Error(data.error)):job.resolve(data.results);};
    this.worker.onerror=()=>this.close(new Error('De vergelijker kon niet starten. Herlaad de pagina en probeer opnieuw.'));
    this.worker.onmessageerror=()=>this.close(new Error('De vergelijker kon het resultaat niet verwerken. Probeer opnieuw.'));
  }
  request(action,payload) {
    if(this.closedError)return Promise.reject(this.closedError);
    return new Promise((resolve,reject)=>{
      const id=++this.sequence;
      const timeout=setTimeout(()=>this.close(new Error('Vergelijken duurt te lang. Probeer een kleinere lijst.')),120000);
      this.pending.set(id,{resolve,reject,timeout});
      try {this.worker.postMessage({id,action,...payload});}
      catch(error){this.close(error);}
    });
  }
  close(error=new Error('Vergelijken gestopt.')) {if(this.closedError)return;this.closedError=error;this.worker.terminate();for(const job of this.pending.values()){clearTimeout(job.timeout);job.reject(error);}this.pending.clear();}
}
