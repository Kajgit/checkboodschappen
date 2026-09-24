import {DatabaseSync} from 'node:sqlite';

/** Durable coordinator storage for one Node process, not a distributed lock.
 * The host must own exactly one coordinator and periodically run due alarms.
 * Keep this file outside the publicly served asset directory.
 */
export class SqliteStorage {
 constructor(path) {
  this.db=new DatabaseSync(path);
  this.db.exec('PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL; PRAGMA busy_timeout=5000;');
  this.db.exec('CREATE TABLE IF NOT EXISTS coordinator_kv (key TEXT PRIMARY KEY,value TEXT NOT NULL)');
  this.sql={exec:(query,...parameters)=>{
   const rows=this.db.prepare(query).all(...parameters);
   return {toArray:()=>rows};
  }};
 }
 async get(key) {
  const row=this.db.prepare('SELECT value FROM coordinator_kv WHERE key=?').get(key);
  return row?JSON.parse(row.value):undefined;
 }
 async put(key,value) {
  this.db.prepare('INSERT OR REPLACE INTO coordinator_kv VALUES(?,?)').run(key,JSON.stringify(value));
 }
 async getAlarm(){return (await this.get('cleanup-alarm'))??null;}
 async setAlarm(timestamp){
  if(!Number.isSafeInteger(timestamp)||timestamp<0)throw new TypeError('Invalid alarm time');
  await this.put('cleanup-alarm',timestamp);
 }
 async deleteAlarm(){this.db.prepare('DELETE FROM coordinator_kv WHERE key=?').run('cleanup-alarm');}
 close(){this.db.close();}
}
