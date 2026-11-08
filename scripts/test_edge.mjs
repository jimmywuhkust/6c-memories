// Runs the future hosted handler against an in-memory HTTP backend; no cloud writes.
import assert from 'node:assert/strict';
import {webcrypto} from 'node:crypto';
if (!globalThis.crypto) globalThis.crypto = webcrypto;
globalThis.Deno = {
  env:{get:key=>({SUPABASE_URL:'https://test.invalid',SUPABASE_SERVICE_ROLE_KEY:'test-only',SIXC_ALLOWED_ORIGINS:'http://localhost:8087'})[key]},
  serve:()=>{},
};
let calls = [], failInsert = false, allowAttempt = true;
globalThis.fetch = async (url, options={}) => {
  calls.push({url,options});
  if (url.includes('sixc_reserve_attempt')) return Response.json(allowAttempt);
  if (url.includes('/rest/v1/sixc_guest_entries?')) {
    assert.match(url,/approved=eq.true/);
    return Response.json([{id:'public',title:'hi',message:'hello',name:'',created_at:'2026-11-08',photo_path:'approved.png'}]);
  }
  if (url.includes('/object/sign/')) return Response.json({signedURL:'/object/sign/sixc-guest-photos/approved.png?token=test'});
  if (url.endsWith('/rest/v1/sixc_guest_entries')) {
    const row=JSON.parse(options.body);
    assert.equal(row.approved,false);
    assert.equal(typeof row.message,'string');
    return failInsert ? new Response('failure',{status:500}) : new Response(null,{status:201});
  }
  if (url.includes('/storage/v1/object/')) return Response.json({});
  throw new Error('Unexpected network request');
};
const {handler} = await import('../private/edge-test/index.js');
const request = (body, origin='http://localhost:8087') => new Request('https://edge.test/?thread=guestbook',{method:'POST',headers:{origin,'content-type':'application/json','x-forwarded-for':'127.0.0.1'},body:JSON.stringify(body)});
const body = {thread:'guestbook',title:'Test',message:'中文 <script>literal text</script>',name:'',approved:true};
let r=await handler(request(body));
assert.equal(r.status,201); assert.equal((await r.json()).status,'pending');
assert.equal(calls.filter(c=>c.url.endsWith('/rest/v1/sixc_guest_entries')).length,1);
r=await handler(request({...body,message:''})); assert.equal(r.status,400);
r=await handler(request(body,'https://unrelated.invalid')); assert.equal(r.status,403);
r=await handler(new Request('https://edge.test/?thread=unknown')); assert.equal(r.status,400);
r=await handler(new Request('https://edge.test/?thread=guestbook',{headers:{origin:'http://localhost:8087'}}));
assert.equal(r.status,200); const listing=await r.json();
assert.match(listing.entries[0].photo_url,/https:\/\/test.invalid\/storage\/v1\/object\/sign\//);
assert.equal('photo_path' in listing.entries[0],false);
r=await handler(request({...body,photo:'data:image/png;base64,bm90YW5pbWFnZQ=='})); assert.equal(r.status,400);
allowAttempt=false; r=await handler(request(body)); assert.equal(r.status,429); allowAttempt=true;
r=await handler(new Request('https://edge.test/',{method:'OPTIONS',headers:{origin:'http://localhost:8087'}}));
assert.equal(r.status,204); assert.equal(r.headers.get('Access-Control-Allow-Origin'),'http://localhost:8087');
failInsert=true; calls=[];
r=await handler(request({...body,photo:'data:image/png;base64,iVBORw0KGgo='}));
assert.equal(r.status,500); assert.ok(calls.some(c=>c.options.method==='DELETE'));
assert.equal((await r.json()).error,'暫時無法送出，請稍後再試。');
console.log('Hosted handler checks passed: validation, moderation, CORS, signed photos, rate limits and failed-upload cleanup.');
