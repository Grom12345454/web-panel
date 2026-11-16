(() => {
  const canvas = document.getElementById('starfield-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d', { alpha: true });
  if (!ctx) return;
  const economyMode = document.body.classList.contains('perf-economy');
  const frameInterval = economyMode ? 88 : 55; // cap low-power devices near 11 fps, standard devices near 18 fps

  const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
  let reduceMotion = motionQuery.matches;
  let width = 0, height = 0, dpr = 1, stars = [], meteors = [];
  let raf = 0, frame = 0, lastTime = 0, nextMeteorAt = 0, lastDrawAt = 0;
  let pointerX = 0, pointerY = 0, parallaxX = 0, parallaxY = 0;
  const rand = (min, max) => min + Math.random() * (max - min);
  const clamp = (v, min, max) => Math.max(min, Math.min(max, v));

  function makeStar() {
    const depth = rand(0.18, 1);
    return {
      x: rand(0, width), y: rand(0, height),
      radius: rand(0.35, 1.55) * (0.55 + depth * 0.65),
      alpha: rand(0.2, 0.86), phase: rand(0, Math.PI * 2),
      pulse: rand(0.006, 0.026), drift: rand(0.025, 0.22) * depth,
      depth, blue: Math.random() < 0.28, cross: Math.random() < 0.045
    };
  }

  function resize() {
    dpr = Math.min(window.devicePixelRatio || 1, economyMode ? 1 : (window.innerWidth < 700 ? 1 : 1.15));
    width = Math.max(1, window.innerWidth);
    height = Math.max(1, window.innerHeight);
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const area = width * height;
    const count = economyMode
      ? Math.round(clamp(area / (width < 700 ? 15000 : 13500), width < 700 ? 20 : 30, width < 700 ? 36 : 58))
      : Math.round(clamp(area / (width < 700 ? 9000 : 7600), width < 700 ? 32 : 55, width < 700 ? 65 : 110));
    stars = Array.from({ length: count }, makeStar);
    meteors = [];
    nextMeteorAt = performance.now() + rand(1800, 4800);
    draw(performance.now(), true);
  }

  function addMeteor(now) {
    if (reduceMotion || economyMode || width < 360 || meteors.length > 1 || now < nextMeteorAt) return;
    const fromLeft = Math.random() < 0.5;
    const startX = fromLeft ? rand(width * 0.08, width * 0.7) : rand(width * 0.3, width * 0.92);
    const startY = rand(-10, height * 0.36);
    const speed = rand(3.2, 6.2);
    meteors.push({ x: startX, y: startY, vx: fromLeft ? speed : -speed, vy: rand(1.7, 3.4),
      length: rand(65, width < 700 ? 115 : 175), life: 0, maxLife: rand(26, 42), alpha: rand(0.45, 0.8) });
    nextMeteorAt = now + rand(4200, 9000);
  }

  function draw(now = performance.now(), staticFrame = false) {
    if (!staticFrame && now - lastDrawAt < frameInterval) {
      raf = requestAnimationFrame(draw);
      return;
    }
    lastDrawAt = now;
    ctx.clearRect(0, 0, width, height);
    const delta = lastTime ? Math.min(2, (now - lastTime) / 16.67) : 1;
    lastTime = now;
    frame++;
    parallaxX += (pointerX - parallaxX) * 0.018;
    parallaxY += (pointerY - parallaxY) * 0.018;

    for (const s of stars) {
      const twinkle = reduceMotion ? 0 : Math.sin(frame * s.pulse + s.phase) * 0.28;
      const alpha = clamp(s.alpha + twinkle, 0.08, 1);
      const px = s.x + parallaxX * s.depth * 9;
      const py = s.y + parallaxY * s.depth * 7;
      ctx.beginPath();
      ctx.fillStyle = s.blue ? `rgba(151,190,255,${alpha})` : `rgba(236,245,255,${alpha})`;
      if (!economyMode && s.radius > 1.05) {
        ctx.shadowBlur = s.radius > 1.45 ? 6 : 3;
        ctx.shadowColor = s.blue ? '#8caeff' : '#d8ebff';
      } else ctx.shadowBlur = 0;
      ctx.arc(px, py, s.radius, 0, Math.PI * 2);
      ctx.fill();

      if (!reduceMotion && s.cross && alpha > 0.66) {
        ctx.shadowBlur = 0;
        ctx.strokeStyle = `rgba(182,211,255,${alpha * 0.36})`;
        ctx.lineWidth = 0.55;
        ctx.beginPath();
        ctx.moveTo(px - 4.5, py); ctx.lineTo(px + 4.5, py);
        ctx.moveTo(px, py - 4.5); ctx.lineTo(px, py + 4.5);
        ctx.stroke();
      }
      if (!reduceMotion && !staticFrame) {
        s.y += s.drift * delta;
        if (s.y > height + 3) { s.y = -3; s.x = rand(0, width); }
      }
    }
    ctx.shadowBlur = 0;

    if (!reduceMotion && !staticFrame) {
      addMeteor(now);
      meteors = meteors.filter(m => m.life < m.maxLife);
      for (const m of meteors) {
        m.x += m.vx * delta; m.y += m.vy * delta; m.life += delta;
        const lifeRatio = m.life / m.maxLife;
        const fade = Math.min(1, lifeRatio * 5, (1 - lifeRatio) * 4) * m.alpha;
        const tailX = m.x - m.vx * (m.length / 7.2);
        const tailY = m.y - m.vy * (m.length / 7.2);
        const gradient = ctx.createLinearGradient(m.x, m.y, tailX, tailY);
        gradient.addColorStop(0, `rgba(235,248,255,${fade})`);
        gradient.addColorStop(0.22, `rgba(139,184,255,${fade * 0.65})`);
        gradient.addColorStop(1, 'rgba(118,145,255,0)');
        ctx.beginPath(); ctx.moveTo(m.x, m.y); ctx.lineTo(tailX, tailY);
        ctx.strokeStyle = gradient; ctx.lineWidth = 1.25; ctx.shadowBlur = 10;
        ctx.shadowColor = '#7aa8ff'; ctx.stroke();
        ctx.beginPath(); ctx.arc(m.x, m.y, 1.25, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(255,255,255,${fade})`; ctx.fill();
      }
      ctx.shadowBlur = 0;
      raf = requestAnimationFrame(draw);
    }
  }

  function stop() { if (raf) cancelAnimationFrame(raf); raf = 0; }
  function start() { stop(); lastTime = 0; draw(performance.now()); }
  function motionChanged(event) {
    reduceMotion = event.matches;
    if (reduceMotion) { stop(); draw(performance.now(), true); }
    else if (!document.hidden) start();
  }

  window.addEventListener('resize', resize, { passive: true });
  if (!economyMode) {
    window.addEventListener('pointermove', event => {
      pointerX = (event.clientX / Math.max(1, width) - 0.5) * 2;
      pointerY = (event.clientY / Math.max(1, height) - 0.5) * 2;
    }, { passive: true });
  }
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) stop();
    else if (!reduceMotion) start();
    else draw(performance.now(), true);
  });
  if (motionQuery.addEventListener) motionQuery.addEventListener('change', motionChanged);
  else if (motionQuery.addListener) motionQuery.addListener(motionChanged);

  resize();
  if (!reduceMotion && !document.hidden) start();
})();
