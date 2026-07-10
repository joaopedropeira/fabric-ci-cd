/* ============================================================
   CI/CD Power BI → Fabric · interações do site
   Vanilla JS, sem dependências.
   ============================================================ */
(() => {
  'use strict';

  const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  document.body.classList.add('has-js');

  /* Paletas por seção (data-theme) --------------------------- */
  const THEMES = {
    violet:  { accent: '#7c5cff', accent2: '#26c6da' },
    rose:    { accent: '#ff5c7c', accent2: '#ff9f68' },
    cyan:    { accent: '#26c6da', accent2: '#4fc3f7' },
    emerald: { accent: '#33d17a', accent2: '#7c5cff' },
    amber:   { accent: '#f2c811', accent2: '#ff9f68' },
  };
  const root = document.documentElement;
  function applyTheme(name) {
    const t = THEMES[name] || THEMES.violet;
    root.style.setProperty('--accent', t.accent);
    root.style.setProperty('--accent-2', t.accent2);
  }

  /* ============================================================
     1) Scroll progress bar
     ============================================================ */
  const progressBar = document.getElementById('progressBar');
  function onScrollProgress() {
    const h = document.documentElement;
    const scrolled = h.scrollTop / (h.scrollHeight - h.clientHeight || 1);
    if (progressBar) progressBar.style.width = (scrolled * 100).toFixed(2) + '%';
  }
  window.addEventListener('scroll', onScrollProgress, { passive: true });
  onScrollProgress();

  /* ============================================================
     2) Scroll-spy robusto (seção que cruza o centro da tela)
     + indicador deslizante no menu + troca de tema
     ============================================================ */
  const sections = Array.from(document.querySelectorAll('.section'));
  const navItems = Array.from(document.querySelectorAll('.nav-item'));
  const indicator = document.getElementById('navIndicator');
  const pathFill = document.getElementById('navPathFill');
  const itemById = {};
  navItems.forEach(a => { itemById[a.getAttribute('href').slice(1)] = a; });

  let currentId = null;

  function moveIndicator(el) {
    if (!indicator || !el) return;
    const isRow = window.matchMedia('(max-width: 960px)').matches;
    if (isRow) {
      indicator.style.transform = `translateX(${el.offsetLeft - 4}px)`;
    } else {
      indicator.style.transform = `translateY(${el.offsetTop - 4}px)`;
    }
  }

  function setActive(id) {
    if (id === currentId) return;
    currentId = id;
    const activeIdx = navItems.findIndex(a => a.getAttribute('href').slice(1) === id);
    navItems.forEach((a, i) => {
      a.classList.toggle('is-active', i === activeIdx);
      a.classList.toggle('reached', i <= activeIdx);   // git-graph: preenche ate o item atual
    });
    const sec = document.getElementById(id);
    if (sec) applyTheme(sec.dataset.theme);
    moveBlobs(sections.findIndex(s => s.id === id));
  }

  // Escolhe a seção cujo centro está mais próximo do centro da viewport.
  function computeActive() {
    const mid = window.innerHeight / 2;
    let best = null, bestDist = Infinity;
    for (const s of sections) {
      const r = s.getBoundingClientRect();
      const center = r.top + r.height / 2;
      const dist = Math.abs(center - mid);
      if (dist < bestDist) { bestDist = dist; best = s; }
    }
    if (best) setActive(best.id);
  }

  let ticking = false;
  window.addEventListener('scroll', () => {
    if (!ticking) {
      window.requestAnimationFrame(() => { computeActive(); ticking = false; });
      ticking = true;
    }
  }, { passive: true });
  window.addEventListener('resize', () => { computeActive(); });
  window.addEventListener('load', computeActive);
  computeActive();

  /* blobs parallax por seção (consulta lazy para evitar TDZ) */
  function moveBlobs(i) {
    if (prefersReduced || i < 0) return;
    const blobs = document.querySelectorAll('.blob');
    const dx = (i % 2 === 0 ? 1 : -1) * 8;
    const dy = (i * 6) % 40;
    blobs.forEach((b, k) => { b.style.transform = `translate(${dx * (k + 1)}px, ${dy * (k % 2 ? -1 : 1)}px)`; });
  }

  /* ============================================================
     3) Reveal on scroll (visivel por padrao; anima como bonus)
     ============================================================ */
  const revealer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) { entry.target.classList.remove('pre'); entry.target.classList.add('in-view'); revealer.unobserve(entry.target); }
    });
  }, { threshold: 0.12, rootMargin: '0px 0px -6% 0px' });
  document.querySelectorAll('.reveal').forEach(el => {
    const r = el.getBoundingClientRect();
    if (r.top < window.innerHeight * 0.92 && r.bottom > 0) {
      el.classList.add('in-view');       // ja visivel: mostra imediatamente
    } else {
      el.classList.add('pre');           // abaixo da dobra: esconde e anima ao entrar
      revealer.observe(el);
    }
  });
  // rede de segurança: garante que nada fique invisível
  window.addEventListener('load', () => {
    setTimeout(() => {
      document.querySelectorAll('.reveal.pre').forEach(el => {
        const r = el.getBoundingClientRect();
        if (r.top < window.innerHeight && r.bottom > 0) { el.classList.remove('pre'); el.classList.add('in-view'); }
      });
    }, 400);
  });

  /* ============================================================
     4) Contadores animados
     ============================================================ */
  function animateCount(el) {
    const target = parseInt(el.dataset.count, 10) || 0;
    const dur = 1400, start = performance.now();
    function tick(now) {
      const p = Math.min((now - start) / dur, 1);
      const eased = 1 - Math.pow(1 - p, 3);
      el.textContent = Math.round(target * eased).toString();
      if (p < 1) requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
  }
  const counters = new IntersectionObserver((entries) => {
    entries.forEach(entry => { if (entry.isIntersecting) { animateCount(entry.target); counters.unobserve(entry.target); } });
  }, { threshold: 0.6 });
  document.querySelectorAll('[data-count]').forEach(el => counters.observe(el));

  /* ============================================================
     5) Cursor glow (desktop)
     ============================================================ */
  const cursor = document.getElementById('cursorGlow');
  if (cursor && window.matchMedia('(pointer: fine)').matches && !prefersReduced) {
    let cx = 0, cy = 0, tx = 0, ty = 0;
    window.addEventListener('mousemove', (e) => { tx = e.clientX; ty = e.clientY; cursor.style.opacity = '1'; });
    window.addEventListener('mouseout', () => { cursor.style.opacity = '0'; });
    (function loop() {
      cx += (tx - cx) * 0.12; cy += (ty - cy) * 0.12;
      cursor.style.transform = `translate(${cx}px, ${cy}px) translate(-50%, -50%)`;
      requestAnimationFrame(loop);
    })();
  }

  /* ============================================================
     6) Constellation background
     ============================================================ */
  const canvas = document.getElementById('constellation');
  if (canvas && !prefersReduced) {
    const ctx = canvas.getContext('2d');
    let w, h, particles, mouse = { x: -9999, y: -9999 };
    const DENSITY = 0.00009, MAX_DIST = 140;
    function resize() {
      w = canvas.width = window.innerWidth * devicePixelRatio;
      h = canvas.height = window.innerHeight * devicePixelRatio;
      canvas.style.width = window.innerWidth + 'px';
      canvas.style.height = window.innerHeight + 'px';
      initParticles();
    }
    function initParticles() {
      const count = Math.min(120, Math.floor(w * h * DENSITY / devicePixelRatio));
      particles = [];
      for (let i = 0; i < count; i++) {
        particles.push({
          x: Math.random() * w, y: Math.random() * h,
          vx: (Math.random() - 0.5) * 0.4 * devicePixelRatio,
          vy: (Math.random() - 0.5) * 0.4 * devicePixelRatio,
          r: (Math.random() * 1.6 + 0.6) * devicePixelRatio,
        });
      }
    }
    function accentRGB() {
      const c = getComputedStyle(root).getPropertyValue('--accent').trim().replace('#', '');
      const hex = c.length === 3 ? c.split('').map(x => x + x).join('') : c;
      const n = parseInt(hex, 16);
      return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 };
    }
    function draw() {
      ctx.clearRect(0, 0, w, h);
      const { r, g, b } = accentRGB();
      const md = MAX_DIST * devicePixelRatio;
      for (let i = 0; i < particles.length; i++) {
        const p = particles[i];
        p.x += p.vx; p.y += p.vy;
        if (p.x < 0 || p.x > w) p.vx *= -1;
        if (p.y < 0 || p.y > h) p.vy *= -1;
        const dxm = mouse.x - p.x, dym = mouse.y - p.y, dm = Math.hypot(dxm, dym);
        if (dm < 180 * devicePixelRatio) { p.x += dxm * 0.008; p.y += dym * 0.008; }
        ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(${r},${g},${b},0.8)`; ctx.fill();
        for (let j = i + 1; j < particles.length; j++) {
          const q = particles[j];
          const dx = p.x - q.x, dy = p.y - q.y, dist = Math.hypot(dx, dy);
          if (dist < md) {
            ctx.beginPath(); ctx.moveTo(p.x, p.y); ctx.lineTo(q.x, q.y);
            ctx.strokeStyle = `rgba(${r},${g},${b},${(1 - dist / md) * 0.5})`;
            ctx.lineWidth = devicePixelRatio * 0.6; ctx.stroke();
          }
        }
      }
      requestAnimationFrame(draw);
    }
    window.addEventListener('mousemove', (e) => { mouse.x = e.clientX * devicePixelRatio; mouse.y = e.clientY * devicePixelRatio; });
    window.addEventListener('mouseout', () => { mouse.x = -9999; mouse.y = -9999; });
    window.addEventListener('resize', resize);
    resize(); draw();
  }

  /* ============================================================
     7) Accent individual de cada gate
     ============================================================ */
  document.querySelectorAll('.gate[data-accent]').forEach(g => g.style.setProperty('--a', g.dataset.accent));

  /* ============================================================
     8) Smooth anchor
     ============================================================ */
  document.querySelectorAll('a[href^="#"]').forEach(a => {
    a.addEventListener('click', (e) => {
      const id = a.getAttribute('href');
      if (id.length > 1) {
        const target = document.querySelector(id);
        if (target) { e.preventDefault(); target.scrollIntoView({ behavior: prefersReduced ? 'auto' : 'smooth', block: 'start' }); }
      }
    });
  });
})();
