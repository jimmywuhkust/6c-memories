(() => {
  const menu = document.querySelector('.menu-toggle');
  const navWrap = document.querySelector('.nav-wrap');
  const closeMenu = () => { navWrap.classList.remove('menu-open'); menu.setAttribute('aria-expanded','false'); menu.setAttribute('aria-label','開啟選單'); };
  menu?.addEventListener('click', () => {
    const open = navWrap.classList.toggle('menu-open');
    menu.setAttribute('aria-expanded', String(open)); menu.setAttribute('aria-label', open ? '關閉選單' : '開啟選單');
  });
  document.addEventListener('click', event => { if (!navWrap.contains(event.target)) closeMenu(); });
  document.addEventListener('keydown', event => { if (event.key==='Escape' && navWrap.classList.contains('menu-open')) { closeMenu(); menu.focus(); } });
  const song = document.querySelector('#class-song');
  const music = document.querySelector('.music-toggle');
  music?.addEventListener('click', async () => {
    if (!song.paused) { song.pause(); return; }
    try { await song.play(); } catch { music.setAttribute('aria-pressed', 'false'); }
  });
  song?.addEventListener('play', () => music.setAttribute('aria-pressed', 'true'));
  song?.addEventListener('pause', () => music.setAttribute('aria-pressed', 'false'));
  song?.addEventListener('ended', () => music.setAttribute('aria-pressed', 'false'));

  const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;

  // Keep the final text in the layout; write characters in without shifting it.
  if (!reduceMotion) {
    document.querySelectorAll('.page-heading h1, .hero-title h1, .entry-heading h1').forEach(heading => {
      const label = heading.dataset.title || heading.textContent.trim();
      heading.setAttribute('aria-label', label);
      heading.querySelectorAll('a').forEach(link => link.setAttribute('aria-label',label));
      const walker = document.createTreeWalker(heading, NodeFilter.SHOW_TEXT);
      const nodes = []; while (walker.nextNode()) nodes.push(walker.currentNode);
      const characters = [];
      nodes.forEach(node => {
        const fragment = document.createDocumentFragment();
        [...node.textContent].forEach(character => {
          const span = document.createElement('span');
          span.className = 'type-char'; span.setAttribute('aria-hidden','true'); span.textContent = character;
          fragment.append(span); characters.push(span);
        });
        node.replaceWith(fragment);
      });
      let shown = 0, start;
      const write = time => {
        start ??= time;
        const count = Math.min(characters.length, Math.floor((time - start) / 58) + 1);
        while (shown < count) {
          characters[shown-1]?.classList.remove('typing-cursor');
          characters[shown].classList.add('is-written','typing-cursor'); shown++;
        }
        if (shown < characters.length) requestAnimationFrame(write);
        else {
          heading.dataset.typingDone = 'true';
          setTimeout(()=>characters.at(-1)?.classList.remove('typing-cursor'),650);
        }
      };
      requestAnimationFrame(write);
    });
  }

  const coverPool = document.querySelector('#gallery-cover-pool');
  if (coverPool) {
    const pool = [...new Map(JSON.parse(coverPool.textContent).map(item=>[item.src,item])).values()];
    for (let i=pool.length-1;i>0;i--) { const j=Math.floor(Math.random()*(i+1)); [pool[i],pool[j]]=[pool[j],pool[i]]; }
    const landscape = pool.findIndex(item=>item.aspect>=1.2 && item.aspect<=2.2);
    if (landscape>0) [pool[0],pool[landscape]]=[pool[landscape],pool[0]];
    document.querySelectorAll('.mosaic-cover img').forEach((image,index) => {
      image.src = pool[index % pool.length].src; image.style.setProperty('--tile-index',index);
    });
  }

  // Choose complete rows together rather than leave holes between photo groups.
  const justify = grid => {
    const tiles = [...grid.querySelectorAll('.photo-tile')], width = Math.floor(grid.getBoundingClientRect().width);
    if (!tiles.length || width<1) return;
    const gap = width<600 ? 6 : 10;
    const target = width>=1050 ? 235 : width>=700 ? 210 : width>=450 ? 180 : 145;
    const maxItems = width<600 ? 3 : 6;
    const ratios = tiles.map(tile => Math.max(.35,Math.min(4,Number(tile.dataset.aspect)||1.5)));
    const cost = Array(tiles.length+1).fill(Infinity), next = Array(tiles.length);
    cost[tiles.length]=0;
    for (let i=tiles.length-1;i>=0;i--) {
      let sum=0;
      for (let j=i;j<Math.min(tiles.length,i+maxItems);j++) {
        sum+=ratios[j];
        const height=(width-gap*(j-i))/sum, relative=height/target;
        let penalty=(relative-1)**2+.08;
        if (relative>1.5) penalty+=(relative-1.5)**2*12;
        if (relative<.62) penalty+=(.62-relative)**2*12;
        if (j===tiles.length-1 && i===j && i>0) penalty+=.4;
        if (penalty+cost[j+1]<cost[i]) { cost[i]=penalty+cost[j+1]; next[i]=j+1; }
      }
    }
    grid.style.setProperty('--photo-gap',gap+'px');
    grid.classList.add('is-justified');
    for (let start=0;start<tiles.length;) {
      const end=next[start] || start+1;
      const sum=ratios.slice(start,end).reduce((a,b)=>a+b,0);
      const available=width-gap*(end-start-1), height=Math.round(available/sum);
      let used=0;
      for (let i=start;i<end;i++) {
        const tileWidth=i===end-1 ? width-gap*(end-start-1)-used : Math.round(available*ratios[i]/sum);
        tiles[i].style.width=tileWidth+'px'; tiles[i].style.height=height+'px';
        used+=tileWidth;
      }
      start=end;
    }
    grid.dataset.layoutReady='true';
  };
  document.querySelectorAll('.photo-grid').forEach(grid => {
    justify(grid);
    let frame;
    new ResizeObserver(()=>{ cancelAnimationFrame(frame); frame=requestAnimationFrame(()=>justify(grid)); }).observe(grid);
  });

  const dialog = document.querySelector('#lightbox');
  const photos = [...document.querySelectorAll('.entry-content img, .gallery .album-photos img')];
  let previousFocus, activePhoto = 0, touchStart;
  const showPhoto = (index, direction = 0) => {
    activePhoto = (index + photos.length) % photos.length;
    const original = photos[activePhoto], enlarged = dialog.querySelector('img');
    enlarged.src = original.dataset.fullUrl || original.src;
    enlarged.alt = original.alt;
    const download = dialog.querySelector('.lightbox-download');
    download.href = original.dataset.downloadUrl || original.dataset.fullUrl || original.src;
    download.download = decodeURIComponent(new URL(download.href,location.href).pathname.split('/').at(-1));
    dialog.querySelector('.lightbox-caption').textContent = original.dataset.event || original.closest('.album')?.querySelector('h2')?.textContent || original.alt || '';
    dialog.querySelector('.lightbox-count').textContent = `${String(activePhoto + 1).padStart(2,'0')} / ${String(photos.length).padStart(2,'0')}`;
    if (!reduceMotion) enlarged.animate([{opacity:0,transform:`translateX(${direction * 24}px) scale(.985)`},{opacity:1,transform:'none'}], {duration:300,easing:'cubic-bezier(.2,.7,.2,1)'});
    if (!dialog.open) dialog.showModal();
    dialog.querySelector('.lightbox-prev').hidden = photos.length < 2;
    dialog.querySelector('.lightbox-next').hidden = photos.length < 2;
  };
  photos.forEach((img, index) => {
    img.tabIndex = 0;
    img.setAttribute('role', 'button');
    img.setAttribute('aria-label', img.alt || '放大照片');
    const open = event => {
      event.preventDefault();
      previousFocus = img;
      showPhoto(index);
    };
    img.addEventListener('click', open);
    img.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') open(event); });
  });
  dialog?.querySelector('.lightbox-close').addEventListener('click', () => dialog.close());
  dialog?.querySelector('.lightbox-prev').addEventListener('click', () => showPhoto(activePhoto - 1, -1));
  dialog?.querySelector('.lightbox-next').addEventListener('click', () => showPhoto(activePhoto + 1, 1));
  dialog?.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
  dialog?.addEventListener('close', () => previousFocus?.focus({preventScroll:true}));
  dialog?.addEventListener('keydown', event => {
    if (event.key === 'ArrowRight') { event.preventDefault(); showPhoto(activePhoto + 1, 1); }
    if (event.key === 'ArrowLeft') { event.preventDefault(); showPhoto(activePhoto - 1, -1); }
  });
  dialog?.addEventListener('touchstart', event => { touchStart = {x:event.changedTouches[0].clientX,y:event.changedTouches[0].clientY}; }, {passive:true});
  dialog?.addEventListener('touchend', event => {
    if (!touchStart) return;
    const dx = event.changedTouches[0].clientX - touchStart.x, dy = event.changedTouches[0].clientY - touchStart.y;
    if (Math.abs(dx)>50 && Math.abs(dx)>Math.abs(dy)*1.3) showPhoto(activePhoto + (dx<0?1:-1), dx<0?1:-1);
    touchStart = null;
  }, {passive:true});

  const videoModal = document.querySelector('#video-modal');
  let videoTrigger;
  document.querySelectorAll('.video-poster').forEach(button => button.addEventListener('click', () => {
    videoTrigger = button;
    const frame = document.createElement('iframe');
    frame.src = `https://www.youtube-nocookie.com/embed/${button.dataset.videoId}?autoplay=1&rel=0`;
    frame.title = button.dataset.videoTitle;
    frame.allow = 'autoplay; fullscreen; encrypted-media; picture-in-picture';
    frame.allowFullscreen = true;
    videoModal.querySelector('.video-screen').replaceChildren(frame);
    videoModal.querySelector('.video-modal-caption span').textContent = button.dataset.videoTitle;
    videoModal.querySelector('a').href = `https://www.youtube.com/watch?v=${button.dataset.videoId}`;
    videoModal.showModal();
  }));
  videoModal?.querySelector('.video-close').addEventListener('click', () => videoModal.close());
  videoModal?.addEventListener('click', event => { if (event.target === videoModal) videoModal.close(); });
  videoModal?.addEventListener('close', () => { videoModal.querySelector('.video-screen').replaceChildren(); videoTrigger?.focus({preventScroll:true}); });

  if (!reduceMotion && 'IntersectionObserver' in window) {
    const reveal = new IntersectionObserver(entries => entries.forEach(entry => {
      if (entry.isIntersecting) { entry.target.classList.add('is-visible'); reveal.unobserve(entry.target); }
    }), {rootMargin:'0px 0px 150px 0px',threshold:.02});
    document.querySelectorAll('.album-heading, .photo-tile, .video-card, .journal-entry').forEach((element,index) => {
      element.classList.add('reveal'); element.style.setProperty('--delay', `${index % 3 * 45}ms`); reveal.observe(element);
    });
  }
  if ('IntersectionObserver' in window) {
    const albumObserver = new IntersectionObserver(entries => entries.forEach(entry => {
      if (!entry.isIntersecting) return;
      document.querySelectorAll('[data-album-link]').forEach(link => {
        if (link.dataset.albumLink === entry.target.id) link.setAttribute('aria-current','true');
        else link.removeAttribute('aria-current');
      });
    }), {rootMargin:'-15% 0px -60% 0px',threshold:0});
    document.querySelectorAll('.album').forEach(album => albumObserver.observe(album));
  }

  const config = window.SIXC_CONFIG || {};
  const local = ['localhost', '127.0.0.1'].includes(location.hostname);
  const endpoint = local ? (config.commentsEndpoint || '/api/guestbook') : (config.commentsEnabled===false ? null : config.commentsEndpoint);
  const headers = config.publishableKey ? {apikey: config.publishableKey} : {};
  async function request(thread, options = {}) {
    const response = await fetch(`${endpoint}?thread=${encodeURIComponent(thread)}`, {...options, headers: {...headers, ...options.headers}});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '暫時無法送出，請稍後再試。');
    return data;
  }
  function renderEntry(entry) {
    const article = document.createElement('article'); article.className = 'guest-entry';
    const author = document.createElement('small'); author.textContent = entry.name || '匿名'; article.append(author);
    if (entry.title) { const h = document.createElement('h3'); h.textContent = entry.title; article.append(h); }
    const p = document.createElement('p'); p.textContent = entry.message; article.append(p);
    if (entry.photo_url && /^https?:\/\//.test(new URL(entry.photo_url, location.href).href)) {
      const img = document.createElement('img'); img.src = entry.photo_url; img.loading = 'lazy'; img.alt = ''; article.append(img);
    }
    const time = document.createElement('time'); time.textContent = new Date(entry.created_at).toLocaleDateString('zh-HK'); article.append(time);
    return article;
  }
  document.querySelectorAll('.comments').forEach(section => {
    const form = section.querySelector('form'), status = section.querySelector('.form-status');
    if (!endpoint) { form.hidden = true; status.textContent = '留言暫時未開放。'; section.append(status); return; }
    request(section.dataset.thread).then(data => {
      (data.entries || []).forEach(entry => section.querySelector('.guest-entries').append(renderEntry(entry)));
    }).catch(() => { status.textContent = '暫時無法載入留言，請稍後再試。'; });
    form.addEventListener('submit', async event => {
      event.preventDefault();
      const button = form.querySelector('button[type=submit]'); button.disabled = true; status.textContent = '';
      try {
        const fields = new FormData(form);
        const payload = {thread: section.dataset.thread, title: fields.get('title') || '', message: fields.get('message'), name: fields.get('name'), website: fields.get('website')};
        const file = fields.get('photo');
        if (file?.size) {
          if (file.size > 8 * 1024 * 1024) throw new Error('照片請小於 8 MB。');
          if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) throw new Error('請選擇 JPG、PNG 或 WebP 照片。');
          payload.photo = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.onerror = reject; reader.readAsDataURL(file); });
        }
        const data = await request(section.dataset.thread, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
        if (data.status !== 'pending') throw new Error('暫時無法確認送出結果，請稍後再試。');
        status.textContent = '已收到，審核後會顯示。'; form.reset();
      } catch (error) { status.textContent = error.message || '暫時無法送出，請稍後再試。'; }
      finally { button.disabled = false; }
    });
  });
})();
