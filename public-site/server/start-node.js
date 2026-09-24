import {mkdir} from 'node:fs/promises';
import {resolve,dirname} from 'node:path';
import {createNodeServer} from './node-server.js';

const port=Number(process.env.PORT||8788),bind=process.env.BIND_ADDRESS||'127.0.0.1';
if(!Number.isInteger(port)||port<1||port>65535)throw new Error('Invalid PORT');
const database=resolve(process.env.COORDINATOR_DATABASE||'.selfhost/coordinator.sqlite');
await mkdir(dirname(database),{recursive:true,mode:0o700});
const env={PUBLIC_APP_URL:process.env.PUBLIC_APP_URL||`http://127.0.0.1:${port}`,
 VISITOR_HASH_SECRET:process.env.VISITOR_HASH_SECRET,
 PRIJSPROFEET_ENABLED:process.env.PRIJSPROFEET_ENABLED||'false',
 PRIJSPROFEET_API_KEY:process.env.PRIJSPROFEET_API_KEY,
 SOURCE_MINUTE_LIMIT:process.env.SOURCE_MINUTE_LIMIT,SOURCE_DAY_LIMIT:process.env.SOURCE_DAY_LIMIT};
const host=await createNodeServer({assets:resolve(process.env.ASSETS_DIRECTORY||'dist'),database,env,
 trustedProxyIps:(process.env.TRUSTED_PROXY_IPS||'').split(',').map(value=>value.trim()).filter(Boolean),onError:message=>console.error(message)});
let stopping=false;
async function stop(){if(stopping)return;stopping=true;await host.close();}
process.once('SIGINT',()=>stop().catch(()=>{process.exitCode=1;}));
process.once('SIGTERM',()=>stop().catch(()=>{process.exitCode=1;}));
host.server.once('error',async error=>{console.error(`HTTP server failed: ${error.code||'unknown'}`);await stop();process.exitCode=1;});
host.server.listen(port,bind,()=>console.log(`Self-host server listening on ${bind}:${port}; PrijsProfeet ${env.PRIJSPROFEET_ENABLED==='true'?'enabled':'disabled'}.`));
