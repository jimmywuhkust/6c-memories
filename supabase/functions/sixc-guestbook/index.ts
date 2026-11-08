// Anonymous guestbook. All database/storage credentials stay inside the function.
const threads = new Set(['guestbook','post-249','post-251','post-256','post-258']);
const base = Deno.env.get('SUPABASE_URL')!;
const secret = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!;
const origins = new Set((Deno.env.get('SIXC_ALLOWED_ORIGINS') || 'http://localhost:8087,https://jimmywuhkust.github.io').split(','));
const backendHeaders = {apikey:secret, Authorization:`Bearer ${secret}`, 'Content-Type':'application/json'};

async function backend(path: string, options: RequestInit = {}) {
  const response = await fetch(base + path, {...options, headers:{...backendHeaders, ...options.headers}});
  if (!response.ok) throw new Error('backend');
  const text = await response.text();
  return text ? JSON.parse(text) : null;
}

export async function handler(req: Request): Promise<Response> {
  const origin = req.headers.get('origin') || '';
  const cors: Record<string,string> = {
    'Content-Type':'application/json; charset=utf-8',
    'Access-Control-Allow-Methods':'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers':'content-type, apikey',
    'Vary':'Origin', 'Cache-Control':'no-store',
  };
  if (origins.has(origin)) cors['Access-Control-Allow-Origin'] = origin;
  const reply = (status: number, body: unknown) => new Response(JSON.stringify(body), {status, headers:cors});
  if (origin && !origins.has(origin)) return reply(403, {error:'無法送出。'});
  if (req.method === 'OPTIONS') return new Response(null, {status:204, headers:cors});
  const thread = new URL(req.url).searchParams.get('thread') || 'guestbook';
  if (!threads.has(thread)) return reply(400, {error:'留言位置不正確。'});
  try {
    if (req.method === 'GET') {
      const entries = await backend('/rest/v1/sixc_guest_entries?select=id,title,message,name,created_at,photo_path&approved=eq.true&thread=eq.' + encodeURIComponent(thread) + '&order=created_at.desc&limit=100');
      for (const entry of entries) {
        entry.photo_url = null;
        if (entry.photo_path) {
          const signed = await backend('/storage/v1/object/sign/sixc-guest-photos/' + entry.photo_path, {method:'POST', body:JSON.stringify({expiresIn:3600})});
          entry.photo_url = base + '/storage/v1' + signed.signedURL;
        }
        delete entry.photo_path;
      }
      return reply(200, {entries});
    }
    if (req.method !== 'POST') return reply(405, {error:'無法送出。'});
    if (!req.headers.get('content-type')?.startsWith('application/json')) return reply(415, {error:'資料格式不正確。'});
    const limit = 12 * 1024 * 1024;
    if (Number(req.headers.get('content-length') || 0) > limit) return reply(413, {error:'照片請小於 8 MB。'});
    // Bound streamed input too: Content-Length is optional and untrusted.
    const reader = req.body?.getReader();
    if (!reader) return reply(400, {error:'資料格式不正確。'});
    const chunks: Uint8Array[] = []; let length = 0;
    for (;;) {
      const {done,value} = await reader.read(); if (done) break;
      length += value.length;
      if (length > limit) { await reader.cancel(); return reply(413, {error:'照片請小於 8 MB。'}); }
      chunks.push(value);
    }
    const all = new Uint8Array(length); let offset = 0;
    for (const chunk of chunks) { all.set(chunk, offset); offset += chunk.length; }
    let data;
    try { data = JSON.parse(new TextDecoder().decode(all)); } catch { return reply(400, {error:'資料格式不正確。'}); }
    if (!data || typeof data !== 'object' || Array.isArray(data)) return reply(400, {error:'資料格式不正確。'});
    const title = String(data.title || '').trim(), message = String(data.message || '').trim(), name = String(data.name || '').trim();
    if (data.website || data.thread !== thread || !message || message.length > 12000 || title.length > 160 || name.length > 80 || (thread === 'guestbook' && !title)) return reply(400, {error:'請檢查留言內容。'});
    const ip = req.headers.get('x-forwarded-for')?.split(',')[0].trim() || 'unknown';
    const fingerprint = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(secret + ip)))).map(b=>b.toString(16).padStart(2,'0')).join('');
    if (!await backend('/rest/v1/rpc/sixc_reserve_attempt', {method:'POST',body:JSON.stringify({p_fingerprint:fingerprint})})) return reply(429, {error:'請稍後再送出留言。'});
    const id = crypto.randomUUID(); let photo_path: string | null = null;
    if (data.photo) {
      const match = /^data:image\/(jpeg|png|webp);base64,([A-Za-z0-9+/=]+)$/.exec(String(data.photo));
      if (!match) return reply(400, {error:'請選擇 JPG、PNG 或 WebP 照片。'});
      let bytes: Uint8Array;
      try { bytes = Uint8Array.from(atob(match[2]), c=>c.charCodeAt(0)); } catch { return reply(400, {error:'照片格式不正確。'}); }
      if (bytes.length > 8 * 1024 * 1024) return reply(413, {error:'照片請小於 8 MB。'});
      const signature = (match[1]==='jpeg' && bytes[0]===255 && bytes[1]===216 && bytes[2]===255) || (match[1]==='png' && [137,80,78,71,13,10,26,10].every((n,i)=>bytes[i]===n)) || (match[1]==='webp' && new TextDecoder().decode(bytes.slice(0,4))==='RIFF' && new TextDecoder().decode(bytes.slice(8,12))==='WEBP');
      if (!signature) return reply(400, {error:'照片格式不正確。'});
      photo_path = id + '.' + match[1];
      const upload = await fetch(base + '/storage/v1/object/sixc-guest-photos/' + photo_path, {method:'POST', headers:{...backendHeaders, 'Content-Type':'image/' + match[1]}, body:bytes});
      if (!upload.ok) throw new Error('upload');
    }
    try {
      await backend('/rest/v1/sixc_guest_entries', {method:'POST',body:JSON.stringify({id,thread,title,message,name,photo_path,approved:false})});
    } catch (error) {
      if (photo_path) await backend('/storage/v1/object/sixc-guest-photos', {method:'DELETE',body:JSON.stringify({prefixes:[photo_path]})}).catch(()=>{});
      throw error;
    }
    return reply(201, {id,status:'pending'});
  } catch {
    return reply(500, {error:'暫時無法送出，請稍後再試。'});
  }
}
Deno.serve(handler);
