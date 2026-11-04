"""Independent reference implementations used only to test frozen validators."""

REFERENCES = [
    {
        "price.js": """exports.lineTotal=(price,qty,discount=0)=>{
          if (!Number.isInteger(qty) || qty<=0) throw Error('quantity');
          if (!Number.isInteger(price) || price<0 || !Number.isFinite(discount) || discount<0 || discount>100) throw Error('price or discount');
          return Math.floor(price*(100-discount)/100)*qty;
        };""",
        "checkout.js": """const {lineTotal}=require('./price');
          exports.checkout=(lines,shipping=0)=>lines.reduce((sum,x)=>sum+lineTotal(x.price,x.qty,x.discount),shipping);""",
    },
    {
        "query.js": """exports.filterAndSort=(rows,term)=>rows.filter(x=>x.title.toLowerCase().includes(term.toLowerCase()))
          .slice().sort((a,b)=>b.createdAt-a.createdAt || a.id.localeCompare(b.id));""",
        "page.js": """exports.page=(rows,page,size)=>({items:rows.slice((page-1)*size,page*size),
          total:rows.length,page,hasNext:page*size<rows.length});""",
    },
    {
        "parse.js": """exports.parseCsv=(text)=>{if (!text) return []; let rows=[],row=[],field='',quoted=false;
          for(let i=0;i<text.length;i++){const ch=text[i];
            if(quoted){if(ch==='\"' && text[i+1]==='\"'){field+='\"';i++;}
              else if(ch==='\"')quoted=false;else field+=ch;}
            else if(ch==='\"')quoted=true;
            else if(ch===','){row.push(field);field='';}
            else if(ch==='\\n'||ch==='\\r'){row.push(field);rows.push(row);row=[];field='';
              if(ch==='\\r'&&text[i+1]==='\\n')i++;}
            else field+=ch;
          } if(field!==''||row.length){row.push(field);rows.push(row);} return rows;};""",
        "import.js": """const {parseCsv}=require('./parse');
          exports.importCustomers=(text)=>{const rows=parseCsv(text);if(!rows.length)return [];
          const seen=new Set(),out=[];for(const row of rows.slice(1)){const id=(row[0]||'').trim();
          const email=(row[1]||'').trim().toLowerCase();
          if(!id||seen.has(id)||!/^\\S+@\\S+\\.\\S+$/.test(email))continue;
          seen.add(id);out.push({id,email});}return out;};""",
    },
    {
        "stock.js": """exports.reserve=(stock,items)=>{const result={...stock};for(const {sku,qty} of items){
          if(!(sku in result))throw Error('unknown sku');if(!Number.isInteger(qty)||qty<=0||result[sku]<qty)
          throw Error('stock quantity');result[sku]-=qty;}return result;};""",
        "order.js": """const {reserve}=require('./stock');exports.placeOrder=(stock,items)=>
          ({stock:reserve(stock,items),totalUnits:items.reduce((n,x)=>n+x.qty,0)});""",
    },
    {
        "scopes.js": """exports.hasPermission=(roles,resource,action)=>roles.some(r=>r.resource===resource &&
          (r.action===action||r.action==='*'));""",
        "authorize.js": """const {hasPermission}=require('./scopes');exports.authorize=(header,subject,resource,action)=>{
          if(!subject||header!=='Bearer '+subject.token)return {status:401};
          if(!hasPermission(subject.roles,resource,action))return {status:403};
          return {status:200,userId:subject.id};};""",
    },
    {
        "signature.js": """const crypto=require('node:crypto');exports.verify=(body,signature,secret)=>{
          if(typeof signature!=='string'||!/^[0-9a-f]{64}$/i.test(signature))return false;
          const a=crypto.createHmac('sha256',secret).update(body).digest(),b=Buffer.from(signature,'hex');
          return a.length===b.length&&crypto.timingSafeEqual(a,b);};""",
        "receiver.js": """const {verify}=require('./signature');exports.receive=(body,signature,secret,seen)=>{
          if(!verify(body,signature,secret))return {accepted:false,duplicate:false};
          const {id}=JSON.parse(body);if(seen.has(id))return {accepted:true,duplicate:true};
          seen.add(id);return {accepted:true,duplicate:false};};""",
    },
    {
        "retry.js": """exports.retry=async(fn,{maxAttempts,baseDelayMs=0,sleep=async()=>{}})=>{
          for(let i=0;;i++){try{return await fn();}catch(e){if(!e.retryable||i+1>=maxAttempts)throw e;
          await sleep(baseDelayMs*2**i);}}};""",
        "client.js": """const {retry}=require('./retry');exports.requestJson=async(fetcher,url,options)=>
          retry(async()=>{const r=await fetcher(url);if(r.status===503)throw Object.assign(Error('503'),{retryable:true});
          if(r.status>=400)throw Error(String(r.status));return r.json();},options);""",
    },
    {
        "cache.js": """exports.createCache=(clock)=>{const m=new Map();return {get(k){const x=m.get(k);
          if(!x||clock()>=x.expires){m.delete(k);return undefined;}return x.value;},
          set(k,value,ttl){m.set(k,{value,expires:clock()+ttl});}};};""",
        "service.js": """const maps=new WeakMap();exports.loadCached=async(cache,key,ttl,loader)=>{
          const found=cache.get(key);if(found!==undefined)return found;if(!maps.has(cache))maps.set(cache,new Map());
          const pending=maps.get(cache);if(pending.has(key))return pending.get(key);
          const p=Promise.resolve().then(loader).then(v=>{cache.set(key,v,ttl);return v;}).finally(()=>pending.delete(key));
          pending.set(key,p);return p;};""",
    },
    {
        "journal.js": """const fs=require('node:fs/promises');exports.readEvents=async(file)=>{let data;
          try{data=await fs.readFile(file,'utf8');}catch(e){if(e.code==='ENOENT')return [];throw e;}
          return data.split(/\\r?\\n/).filter(x=>x.trim()).map(x=>JSON.parse(x));};
          exports.appendEvent=async(file,event)=>{if(!event||typeof event.id!=='string'||!event.id.trim())
          throw Error('invalid event');await fs.appendFile(file,JSON.stringify(event)+'\\n','utf8');};""",
        "handler.js": """const {readEvents,appendEvent}=require('./journal');exports.createHandler=file=>async req=>{
          if(req.path!=='/events')return {status:404,body:{error:'not found'}};
          if(req.method==='GET')return {status:200,body:await readEvents(file)};
          if(req.method==='POST'){if(!req.body||typeof req.body.id!=='string'||!req.body.id.trim())
          return {status:400,body:{error:'invalid event'}};await appendEvent(file,req.body);
          return {status:201,body:{id:req.body.id}};}return {status:404,body:{error:'not found'}};};""",
    },
]
