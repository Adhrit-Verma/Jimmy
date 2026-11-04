// Shared behaviour for every page. Everything here is an enhancement: without it the pages read
// the same, clips show their poster, every tab panel after the first stays reachable by its link.
(function () {
  var motion = !window.matchMedia || window.matchMedia('(prefers-reduced-motion: no-preference)').matches;
  var io = 'IntersectionObserver' in window;
  function seen(el, fn, opts) {
    if (!io) return fn(true);
    new IntersectionObserver(function (es) { es.forEach(function (e) { fn(e.isIntersecting, e); }); }, opts || { threshold: 0.35 }).observe(el);
  }

  // Looping clips from the trailer: play only while on screen, never with reduced motion.
  document.querySelectorAll('video[data-loop]').forEach(function (v) {
    v.muted = true; v.loop = true; v.playsInline = true;
    if (!motion) return;
    seen(v, function (on) {
      if (on) { if (!v.src) v.src = v.dataset.src; var p = v.play(); if (p && p.catch) p.catch(function () {}); }
      else v.pause();
    });
  });

  // Copy buttons on code blocks.
  document.querySelectorAll('.code').forEach(function (block) {
    if (!navigator.clipboard) return;
    var b = document.createElement('button');
    b.type = 'button'; b.className = 'copy'; b.textContent = 'Copy';
    b.addEventListener('click', function () {
      navigator.clipboard.writeText(block.querySelector('pre').innerText).then(function () {
        b.textContent = 'Copied'; setTimeout(function () { b.textContent = 'Copy'; }, 1500);
      });
    });
    block.appendChild(b);
  });

  // Tabs: [data-tabs] holds role=tab buttons that point at their panels.
  document.querySelectorAll('[data-tabs]').forEach(function (list) {
    var tabs = [].slice.call(list.querySelectorAll('[role=tab]'));
    function pick(t, focus) {
      tabs.forEach(function (b) {   // hide first, then show: in the chapter player every tab shares one panel
        var on = b === t; b.setAttribute('aria-selected', on); b.tabIndex = on ? 0 : -1;
        document.getElementById(b.getAttribute('aria-controls')).hidden = true;
      });
      document.getElementById(t.getAttribute('aria-controls')).hidden = false;
      if (focus) t.focus();
      list.dispatchEvent(new CustomEvent('pick', { detail: tabs.indexOf(t) }));
    }
    tabs.forEach(function (b, i) {
      b.addEventListener('click', function () { pick(b); });
      b.addEventListener('keydown', function (e) {
        var d = e.key === 'ArrowRight' || e.key === 'ArrowDown' ? 1 : e.key === 'ArrowLeft' || e.key === 'ArrowUp' ? -1 : 0;
        if (d) { e.preventDefault(); pick(tabs[(i + d + tabs.length) % tabs.length], true); }
      });
    });
    list._pick = pick; list._tabs = tabs;
  });

  // The chapter player: each chapter is a clip; it moves to the next one when a clip ends.
  var reel = document.querySelector('.reel');
  if (reel) {
    var list = reel.querySelector('[data-tabs]'), vid = reel.querySelector('video'), auto = motion;
    var chapters = list._tabs;
    function show(i) {
      var c = chapters[i];
      vid.poster = c.dataset.poster;
      vid.src = c.dataset.clip; vid.loop = false;
      reel.style.setProperty('--dur', (c.dataset.dur || 6) + 's');
      reel.classList.remove('run'); void reel.offsetWidth;
      if (auto) { var p = vid.play(); if (p && p.catch) p.catch(function () {}); reel.classList.add('run'); }
    }
    list.addEventListener('pick', function (e) {
      show(e.detail);
      var b = chapters[e.detail];   // on phones the chapters are a sideways strip: keep the playing one in view
      if (list.scrollWidth > list.clientWidth) list.scrollTo({ left: b.offsetLeft - 8, behavior: motion ? 'smooth' : 'auto' });
    });
    vid.addEventListener('ended', function () {
      var i = chapters.findIndex(function (b) { return b.getAttribute('aria-selected') === 'true'; });
      list._pick(chapters[(i + 1) % chapters.length]);
    });
    vid.muted = true; vid.playsInline = true; vid.controls = !motion;
    if (!motion) list.addEventListener('pick', function () { vid.loop = true; });
    if (motion) seen(reel, function (on) {
      if (on && !vid.src) show(0);
      else if (on) vid.play().catch(function () {});
      else vid.pause();
    });
  }

  // The trailer: the poster is a button; the real player loads only when asked.
  document.querySelectorAll('[data-trailer]').forEach(function (b) {
    b.addEventListener('click', function () {
      var v = document.createElement('video');
      v.src = b.dataset.trailer; v.poster = b.dataset.poster; v.controls = true; v.playsInline = true; v.autoplay = true;
      v.setAttribute('aria-label', b.getAttribute('aria-label'));
      b.replaceWith(v); v.focus();
    });
  });

  // Numbers count up once, the first time they're seen.
  if (motion) document.querySelectorAll('[data-count]').forEach(function (n) {
    var to = parseFloat(n.dataset.count), dec = (n.dataset.count.split('.')[1] || '').length, done = false;
    n.textContent = (0).toFixed(dec);
    seen(n, function (on) {
      if (!on || done) return; done = true;
      var t0 = null;
      (function f(t) { if (!t0) t0 = t; var p = Math.min(1, (t - t0) / 900), e = 1 - Math.pow(1 - p, 3);
        n.textContent = (to * e).toFixed(dec); if (p < 1) requestAnimationFrame(f); })(performance.now());
    });
  });

  // Docs-style pages: the table of contents follows the reader, and a thin bar shows how far.
  var toc = document.querySelector('.toc');
  if (toc) {
    var bar = document.createElement('div'); bar.className = 'readbar'; bar.setAttribute('aria-hidden', 'true');
    document.body.appendChild(bar);
    var links = [].slice.call(toc.querySelectorAll('a[href^="#"]'));
    var secs = links.map(function (a) { return document.getElementById(a.getAttribute('href').slice(1)); });
    function onScroll() {
      var h = document.documentElement, max = h.scrollHeight - h.clientHeight;
      bar.style.transform = 'scaleX(' + (max > 0 ? h.scrollTop / max : 0) + ')';
      var cur = 0;
      secs.forEach(function (s, i) { if (s && s.getBoundingClientRect().top < innerHeight * 0.3) cur = i; });
      links.forEach(function (a, i) { a.classList.toggle('active', i === cur); });
    }
    addEventListener('scroll', onScroll, { passive: true }); onScroll();
  }
})();
