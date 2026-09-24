/** Shopping lists never leave this device through this module. */
export const MAX_ITEMS = 200;
const units = new Set(['verpakking','stuk','g','kg','ml','l']);
export function validateList(value) {
  if (!value || value.version !== 1 || !Array.isArray(value.items) || value.items.length > MAX_ITEMS) {
    throw new Error('Ongeldig lijstbestand (maximaal 200 regels).');
  }
  const ids = new Set();
  const items = value.items.map(item => {
    if (!item || typeof item.id !== 'string' || !/^[\w-]{1,80}$/.test(item.id) || ids.has(item.id) ||
        typeof item.query !== 'string' || !item.query.trim() || item.query.length > 150 ||
        /[\x00-\x1f]/.test(item.query) || !Number.isFinite(item.quantity) || item.quantity <= 0 ||
        item.quantity > 100000 || !units.has(item.unit)) throw new Error('Ongeldige productregel.');
    ids.add(item.id);
    return {id:item.id,query:item.query.trim(),quantity:item.quantity,unit:item.unit};
  });
  const postcode = typeof value.postcode === 'string' ? value.postcode.replace(/\s/g,'').toUpperCase() : '';
  if (postcode && !/^[1-9]\d{3}[A-Z]{2}$/.test(postcode)) throw new Error('Ongeldige postcode.');
  return {version:1,items,postcode};
}
export const emptyList = () => ({version:1,items:[],postcode:''});
export function parseBackup(json) {
  if (typeof json !== 'string' || json.length > 100000) throw new Error('Het lijstbestand is te groot.');
  try {return validateList(JSON.parse(json));}
  catch(error) {throw new Error(`Import mislukt: ${error.message}`);}
}
export function serializeBackup(list) {return JSON.stringify(validateList(list),null,2);}
export class ListStore {
  constructor({indexedDB=globalThis.indexedDB,name='boodschappenwijzer'}={}) {this.indexedDB=indexedDB;this.name=name;}
  async open() {
    if (this.db) return this.db;
    if (!this.indexedDB) throw new Error('Deze browser ondersteunt geen lokale lijstopslag.');
    if (!this.opening) this.opening=new Promise((resolve,reject)=>{
      const request=this.indexedDB.open(this.name,1);
      request.onupgradeneeded=()=>request.result.createObjectStore('private');
      request.onerror=()=>reject(new Error('Lokale opslag kon niet worden geopend.'));
      request.onblocked=()=>reject(new Error('Sluit andere tabbladen om de opslag bij te werken.'));
      request.onsuccess=()=>{this.db=request.result;this.db.onversionchange=()=>this.close();resolve(this.db);};
    }).catch(error=>{this.opening=null;throw error;});
    return this.opening;
  }
  async transaction(mode,operation) {
    const db=await this.open();
    return new Promise((resolve,reject)=>{
      const tx=db.transaction('private',mode);let value;
      const request=operation(tx.objectStore('private'));
      request.onsuccess=()=>{value=request.result;};
      tx.oncomplete=()=>resolve(value);
      tx.onabort=()=>reject(new Error('Wijzigingen zijn niet opgeslagen. Maak een reservekopie en controleer de browseropslag.'));
      tx.onerror=()=>{}; // onabort reports failure; never claim a successful request is a committed write.
    });
  }
  async load() {const value=await this.transaction('readonly',s=>s.get('list'));return value ? validateList(value) : emptyList();}
  async save(value) {const list=validateList(value);await this.transaction('readwrite',s=>s.put(list,'list'));return list;}
  async clear() {await this.transaction('readwrite',s=>s.clear());}
  close() {this.db?.close();this.db=null;this.opening=null;}
}
