"""Reproducible, independent, multi-file coding work, never scored by an LLM.

Nine scenario types replicated into 16 isolated projects to balance the 16-agent
stage. Tests are assembled from this installed runner, not copied to worktrees.
"""
from __future__ import annotations
import hashlib
import json
import time
from pathlib import Path
from .common import BenchmarkError, require_success, run_command, remaining
from .fixtures import create_worktree

SCENARIOS = [
    {
        "title": "Order totals and checkout",
        "instructions": "Implement cents-safe line pricing, percentage discount floor rounding, totals with optional shipping, and reject invalid quantities. Make pricing and checkout modules work together.",
        "files": {"price.js": "exports.lineTotal=(price,qty,discount=0)=>{throw Error('TODO')};",
                  "checkout.js": "exports.checkout=(lines,shipping=0)=>{throw Error('TODO')};"},
        "tests": """const {lineTotal}=require('./src/price');
const {checkout}=require('./src/checkout');
assert.equal(lineTotal(1999,2,10),3598);
assert.equal(lineTotal(100,3,0),300);
assert.throws(()=>lineTotal(100,0),/quantity/i);
assert.equal(checkout([{price:500,qty:2,discount:10},{price:250,qty:1}],100),1250);"""
    },
    {
        "title": "Search and cursor-free pagination",
        "instructions": "Implement case-insensitive title filtering and stable descending createdAt ordering (break ties by ascending id). Paginate with 1-based page numbers; return items,total,page,hasNext.",
        "files": {"query.js": "exports.filterAndSort=(rows,term)=>{throw Error('TODO')};",
                  "page.js": "exports.page=(rows,page,size)=>{throw Error('TODO')};"},
        "tests": """const {filterAndSort}=require('./src/query');
const {page}=require('./src/page');
const a=[{id:'b',title:'Node App',createdAt:2},{id:'a',title:'node API',createdAt:2},{id:'c',title:'Rust',createdAt:4}];
assert.deepEqual(filterAndSort(a,'NODE').map(x=>x.id),['a','b']);
assert.equal(a[0].id,'b');
assert.deepEqual(page([1,2,3,4,5],2,2),{items:[3,4],total:5,page:2,hasNext:true});
assert.deepEqual(page([1],2,2),{items:[],total:1,page:2,hasNext:false});"""
    },
    {
        "title": "CSV customer import",
        "instructions": "Parse RFC-style comma-delimited rows with double-quoted commas, escaped quotes and CRLF; return row arrays. Implement importCustomers(csv) with id and normalized lowercase email; reject malformed emails and duplicate IDs.",
        "files": {"parse.js": "exports.parseCsv=(text)=>{throw Error('TODO')};",
                  "import.js": "exports.importCustomers=(text)=>{throw Error('TODO')};"},
        "tests": """const {parseCsv}=require('./src/parse');
const {importCustomers}=require('./src/import');
assert.deepEqual(parseCsv('id,name\\r\\n1,\"Doe, Jane\"\\r\\n2,\"A\"\"B\"'),[['id','name'],['1','Doe, Jane'],['2','A\"B']]);
assert.deepEqual(importCustomers('id,email\\n1, A@EXAMPLE.COM \\n2,wrong\\n1,b@x.com'),[{id:'1',email:'a@example.com'}]);
assert.deepEqual(importCustomers('id,email\\n'),[]);"""
    },
    {
        "title": "Atomic inventory reservation",
        "instructions": "Implement immutable reserve(stock,items) returning an updated object; coalesce repeated SKU quantities and reject unavailable products or insufficient stock without mutating input. placeOrder returns {stock,totalUnits}.",
        "files": {"stock.js": "exports.reserve=(stock,items)=>{throw Error('TODO')};",
                  "order.js": "exports.placeOrder=(stock,items)=>{throw Error('TODO')};"},
        "tests": """const {reserve}=require('./src/stock');
const {placeOrder}=require('./src/order');
const s={a:5,b:2};
assert.deepEqual(reserve(s,[{sku:'a',qty:2},{sku:'a',qty:1}]),{a:2,b:2});
assert.deepEqual(s,{a:5,b:2});
assert.throws(()=>reserve(s,[{sku:'b',qty:3}]),/stock|quantity/i);
assert.throws(()=>reserve(s,[{sku:'x',qty:1}]),/unknown|missing|sku/i);
assert.deepEqual(placeOrder(s,[{sku:'a',qty:1},{sku:'b',qty:2}]),{stock:{a:4,b:0},totalUnits:3});"""
    },
    {
        "title": "API permissions and authorization",
        "instructions": "Implement permission check with exact resource and action (wildcard '*' allowed as action), and authorize(authHeader, subject, resource, action) returning {status,userId} for success or {status:401/403} otherwise.",
        "files": {"scopes.js": "exports.hasPermission=(roles,resource,action)=>{throw Error('TODO')};",
                  "authorize.js": "exports.authorize=(header,subject,resource,action)=>{throw Error('TODO')};"},
        "tests": """const {hasPermission}=require('./src/scopes');
const {authorize}=require('./src/authorize');
assert.equal(hasPermission([{resource:'tickets',action:'read'}],'tickets','read'),true);
assert.equal(hasPermission([{resource:'tickets',action:'read'}],'billing','read'),false);
assert.equal(hasPermission([{resource:'tickets',action:'*'}],'tickets','delete'),true);
assert.deepEqual(authorize('Bearer abc',{id:'u1',token:'abc',roles:[{resource:'tickets',action:'read'}]},'tickets','read'),{status:200,userId:'u1'});
assert.deepEqual(authorize('wrong',{id:'u1',token:'abc',roles:[]},'tickets','read'),{status:401});
assert.deepEqual(authorize('Bearer abc',{id:'u1',token:'abc',roles:[]},'tickets','write'),{status:403});"""
    },
    {
        "title": "Signed and idempotent webhook receiver",
        "instructions": "Implement HMAC SHA-256 hex signature verification with constant-time comparison, and receive(body,signature,secret,seenSet) which rejects invalid signatures and deduplicates event IDs; record only successfully processed IDs.",
        "files": {"signature.js": "exports.verify=(body,signature,secret)=>{throw Error('TODO')};",
                  "receiver.js": "exports.receive=(body,signature,secret,seen)=>{throw Error('TODO')};"},
        "tests": """const crypto=require('node:crypto');
const {verify}=require('./src/signature');
const {receive}=require('./src/receiver');
const body=JSON.stringify({id:'evt-1',type:'order.created'}),secret='sample-secret';
const signature=crypto.createHmac('sha256',secret).update(body).digest('hex');
assert.equal(verify(body,signature,secret),true);
assert.equal(verify(body,'wrong',secret),false);
const seen=new Set();
assert.deepEqual(receive(body,signature,secret,seen),{accepted:true,duplicate:false});
assert.deepEqual(receive(body,signature,secret,seen),{accepted:true,duplicate:true});
assert.deepEqual(receive(body,'wrong',secret,seen),{accepted:false,duplicate:false});"""
    },
    {
        "title": "Async retry with injectable delays",
        "instructions": "Implement retry(fn,{maxAttempts,baseDelayMs,sleep}) for retryable errors marked retryable=true, exponential delays, no retry on other errors. Implement requestJson(fetcher,url,options) to retry HTTP 503 and parse success JSON; reject HTTP 404 directly.",
        "files": {"retry.js": "exports.retry=async(fn,options)=>{throw Error('TODO')};",
                  "client.js": "exports.requestJson=async(fetcher,url,options)=>{throw Error('TODO')};"},
        "tests": """const {retry}=require('./src/retry');
const {requestJson}=require('./src/client');
const waits=[];let n=0;
assert.equal(await retry(async()=>{if(++n<3)throw Object.assign(Error('retry'),{retryable:true});return 42},{maxAttempts:4,baseDelayMs:10,sleep:async ms=>waits.push(ms)}),42);
assert.deepEqual(waits,[10,20]);
let tries=0;
assert.deepEqual(await requestJson(async()=>{tries++;return tries===1?{status:503}:{status:200,json:async()=>({ok:true})}},'/api',{maxAttempts:3,baseDelayMs:1,sleep:async()=>{}}),{ok:true});
assert.equal(tries,2);
await assert.rejects(requestJson(async()=>({status:404}),'/missing',{maxAttempts:3,sleep:async()=>{}}),/404/);"""
    },
    {
        "title": "TTL cache and concurrent request coalescing",
        "instructions": "Implement createCache(clock) with get/set(key,value,ttlMs), expiry and no stale reads. Implement loadCached(cache,key,ttlMs,loader) to reuse valid cache and deduplicate in-flight loads; never cache rejected promises.",
        "files": {"cache.js": "exports.createCache=(clock)=>{throw Error('TODO')};",
                  "service.js": "exports.loadCached=async(cache,key,ttlMs,loader)=>{throw Error('TODO')};"},
        "tests": """const {createCache}=require('./src/cache');
const {loadCached}=require('./src/service');
let now=100;const c=createCache(()=>now);
c.set('x',2,10);assert.equal(c.get('x'),2);now=111;assert.equal(c.get('x'),undefined);
let count=0;
const load=async()=>{count++;await Promise.resolve();return 'ok';};
const values=await Promise.all([loadCached(c,'y',50,load),loadCached(c,'y',50,load)]);
assert.deepEqual(values,['ok','ok']);assert.equal(count,1);
assert.equal(await loadCached(c,'y',50,load),'ok');assert.equal(count,1);"""
    },
    {
        "title": "File-backed event journal and API handler",
        "instructions": "Implement async readEvents(file) and appendEvent(file,event) for a UTF-8 JSON-lines journal. A missing file reads as an empty list, blank lines are ignored, malformed JSON is rejected, and events without a nonempty string id are rejected. Implement createHandler(file), returning an async handler for {method,path,body}: GET /events returns {status:200,body:events}; valid POST /events appends and returns {status:201,body:{id}}; invalid events return {status:400,body:{error:'invalid event'}}; other routes return {status:404,body:{error:'not found'}}.",
        "files": {"journal.js": "exports.readEvents=async(file)=>{throw Error('TODO')};exports.appendEvent=async(file,event)=>{throw Error('TODO')};",
                  "handler.js": "exports.createHandler=(file)=>{throw Error('TODO')};"},
        "tests": """const fs=require('node:fs'),path=require('node:path');
const {readEvents,appendEvent}=require('./src/journal');
const {createHandler}=require('./src/handler');
const dir=fs.mkdtempSync(path.join(process.cwd(),'.tsbench-validator-')),file=path.join(dir,'events.jsonl');
try {
  assert.deepEqual(await readEvents(file),[]);
  await appendEvent(file,{id:'a',value:1});await appendEvent(file,{id:'b',value:2});
  assert.deepEqual(await readEvents(file),[{id:'a',value:1},{id:'b',value:2}]);
  await assert.rejects(async()=>appendEvent(file,{id:''}));
  const handler=createHandler(file);
  assert.deepEqual(await handler({method:'POST',path:'/events',body:{id:'c'}}),{status:201,body:{id:'c'}});
  assert.deepEqual(await handler({method:'POST',path:'/events',body:{}}),{status:400,body:{error:'invalid event'}});
  assert.deepEqual(await handler({method:'GET',path:'/events'}),{status:200,body:[{id:'a',value:1},{id:'b',value:2},{id:'c'}]});
  assert.deepEqual(await handler({method:'GET',path:'/unknown'}),{status:404,body:{error:'not found'}});
  fs.appendFileSync(file,'not-json\\n');await assert.rejects(async()=>readEvents(file));
} finally {fs.rmSync(dir,{recursive:true,force:true});}"""
    }
]

TASK_COUNT=16


def digest() -> str:
    return hashlib.sha256(json.dumps(SCENARIOS,sort_keys=True).encode()).hexdigest()


def task_prompt(index: int) -> str:
    if index<0 or index>=TASK_COUNT:
        raise BenchmarkError("Unknown real coding task")
    s=SCENARIOS[index%len(SCENARIOS)]
    return ("You are working on a multi-file Node.js application exercise. "+
            "Implement the feature: "+s["title"]+". "+s["instructions"]+
            " Modify only the files in tasks/"+str(index).zfill(2)+"/src; "+
            "the tests are independently maintained. Do not install dependencies. "+
            "Run your own checks if useful and finish once the implementation is correct.")


def create_real_base(root: Path) -> Path:
    base=root/"real-fixture-base"
    base.mkdir(parents=True,exist_ok=False)
    for idx in range(TASK_COUNT):
        info=SCENARIOS[idx%len(SCENARIOS)]
        folder=base/"tasks"/str(idx).zfill(2)/"src"
        folder.mkdir(parents=True)
        for name,code in info["files"].items():
            (folder/name).write_text(code+"\n",encoding="utf-8")
    (base/"README.md").write_text("TermSquad v1.1 frozen multi-file application fixtures.\n")
    require_success(run_command(["git","init","-q",str(base)],10),"real fixture git init")
    require_success(run_command(["git","-C",str(base),"add","."],10),"real fixture git add")
    require_success(run_command(["git","-C",str(base),"-c","user.name=TermSquad Benchmark",
                                 "-c","user.email=benchmark@localhost","commit","-qm","freeze real fixtures"],10),
                    "real fixture git commit")
    return base


def changes_within_scope(worktree: Path, task_ids: set[int], timeout: float) -> bool:
    deadline=time.monotonic()+timeout
    commands=(["git","-C",str(worktree),"diff","--name-only","--no-renames","-z","HEAD","--"],
              ["git","-C",str(worktree),"ls-files","--others","-z"])
    allowed=tuple("tasks/"+str(i).zfill(2)+"/src/" for i in sorted(task_ids))
    for command in commands:
        response=run_command(command,remaining(deadline,timeout),max_output=200000)
        output=require_success(response,"git scope check")
        if len(output)>=200000:
            raise BenchmarkError("Scope listing exceeds safe limit")
        if any(not name.startswith(allowed) for name in output.split("\0") if name):
            return False
    return True


def validate_task(index: int, worktree: Path, timeout: float = 12.0) -> dict:
    if index<0 or index>=TASK_COUNT:
        raise BenchmarkError("Unknown real coding task")
    scenario=SCENARIOS[index%len(SCENARIOS)]
    source_path=worktree/"tasks"/str(index).zfill(2)
    code="const assert=require('node:assert/strict');"+scenario["tests"]
    # Test script is runner-owned, and never written into agent-owned source files.
    try:
        response=run_command(["node","-e","(async()=>{"+code+";console.log('PASS')})().catch(e=>{console.error(e);process.exit(1)})"],
                             timeout,cwd=source_path,max_output=1500)
        return {"passed":response["returncode"]==0 and "PASS" in response["stdout"],
                "elapsed_seconds":response["elapsed_seconds"]}
    except Exception:
        return {"passed":False,"elapsed_seconds":None}
