/* 设计稿共用脚本：SVG 图标注入、主题切换、通用交互（仅供预览，不进入生产代码） */

/* ---------------- 内联 SVG sprite（取代 Font Awesome CDN） ---------------- */
const SPRITE = `
<svg style="display:none" xmlns="http://www.w3.org/2000/svg">
  <symbol id="i-list" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M8 6h13M8 12h13M8 18h13M3.5 6h.01M3.5 12h.01M3.5 18h.01"/></symbol>
  <symbol id="i-plus" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 5v14M5 12h14"/></symbol>
  <symbol id="i-bell" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/></symbol>
  <symbol id="i-history" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l4 2"/></symbol>
  <symbol id="i-user" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3.6-6 8-6s8 2 8 6"/></symbol>
  <symbol id="i-search" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><circle cx="11" cy="11" r="7"/><path d="m16.5 16.5 4 4"/></symbol>
  <symbol id="i-refresh" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M21 12a9 9 0 1 1-3-6.7"/><path d="M21 3v6h-6"/></symbol>
  <symbol id="i-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M21 13A9 9 0 1 1 11 3a7 7 0 0 0 10 10Z"/></symbol>
  <symbol id="i-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M19.1 4.9l-1.4 1.4M6.3 17.7l-1.4 1.4"/></symbol>
  <symbol id="i-edit" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></symbol>
  <symbol id="i-trash" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14"/></symbol>
  <symbol id="i-chart" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3 3v18h18"/><path d="m7 15 4-5 3 3 5-7"/></symbol>
  <symbol id="i-info" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/></symbol>
  <symbol id="i-arrow-up" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 19V5M5 12l7-7 7 7"/></symbol>
  <symbol id="i-arrow-down" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14M19 12l-7 7-7-7"/></symbol>
  <symbol id="i-minus" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12h14"/></symbol>
  <symbol id="i-cog" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-2.7 1.1V21a2 2 0 1 1-4 0v-.1A1.6 1.6 0 0 0 7.5 19.4l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1A1.6 1.6 0 0 0 3 14.9H3a2 2 0 1 1 0-4h.1A1.6 1.6 0 0 0 4.6 8.4l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1A1.6 1.6 0 0 0 10 4.5V4a2 2 0 1 1 4 0v.1a1.6 1.6 0 0 0 2.7 1.1l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1A1.6 1.6 0 0 0 21 11h.1a2 2 0 1 1 0 4H21a1.6 1.6 0 0 0-1.6 1Z"/></symbol>
  <symbol id="i-gauge" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 14 8 9"/><path d="M20.5 18a9.5 9.5 0 1 0-17 0"/><path d="M3.5 18h17"/></symbol>
  <symbol id="i-sparkles" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 3l1.8 4.7L18.5 9.5 13.8 11.3 12 16l-1.8-4.7L5.5 9.5l4.7-1.8Z"/><path d="M18 16.5l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8Z"/></symbol>
  <symbol id="i-mail" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/></symbol>
  <symbol id="i-lock" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="4" y="10" width="16" height="10" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></symbol>
  <symbol id="i-eye" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></symbol>
  <symbol id="i-eye-off" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3 3l18 18"/><path d="M10.6 10.6a3 3 0 0 0 4.2 4.2"/><path d="M6.7 6.8C4 8.3 2 12 2 12s3.6 7 10 7c2 0 3.7-.7 5.2-1.6"/><path d="M9.9 5.2A10 10 0 0 1 12 5c6.4 0 10 7 10 7a18 18 0 0 1-2.4 3.3"/></symbol>
  <symbol id="i-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="m4 12.5 5 5L20 6.5"/></symbol>
  <symbol id="i-send" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M21 3 3 10.5l7 3 3 7Z"/><path d="M21 3l-8 17"/></symbol>
  <symbol id="i-trend-down" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="m3 7 7 7 4-4 7 7"/><path d="M21 17v-6h-6"/></symbol>
  <symbol id="i-alert" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 3 2 20h20L12 3Z"/><path d="M12 9v5M12 17h.01"/></symbol>
</svg>`;

/* ---------------- 主题 ---------------- */
const THEME_KEY = 'stock-ui-theme';

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  const icon = document.querySelector('#theme-icon');
  if (icon) icon.setAttribute('href', theme === 'dark' ? '#i-moon' : '#i-sun');
  try { localStorage.setItem(THEME_KEY, theme); } catch (e) { /* file:// 下可能不可用 */ }
}

function initTheme() {
  let saved = null;
  try { saved = localStorage.getItem(THEME_KEY); } catch (e) { /* noop */ }
  applyTheme(saved || 'dark');
  const btn = document.getElementById('theme-btn');
  if (btn) {
    btn.addEventListener('click', () => {
      applyTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
    });
  }
}

/* ---------------- 通用交互 ---------------- */
function initTabs() {
  document.querySelectorAll('[data-tabs]').forEach(group => {
    group.querySelectorAll('.tab').forEach(tab => {
      tab.addEventListener('click', () => {
        group.querySelectorAll('.tab').forEach(t => t.classList.toggle('on', t === tab));
        const scope = tab.closest('.card') || document;
        scope.querySelectorAll('[data-body]').forEach(b => {
          b.classList.toggle('hidden', b.dataset.body !== tab.dataset.tab);
        });
      });
    });
  });
}

function initLadders() {
  const refresh = scope => {
    scope.querySelectorAll('.ladder').forEach(ladder => {
      const cur = parseFloat(ladder.dataset.current);
      ladder.querySelectorAll('.ladder-row').forEach(row => {
        const input = row.querySelector('[data-ladder]');
        const out = row.querySelector('.delta');
        if (!input || !out) return;
        const v = parseFloat(input.value);
        if (!isFinite(v) || !isFinite(cur) || cur === 0) { out.textContent = '—'; out.className = 'delta'; return; }
        const pct = (v - cur) / cur * 100;
        out.textContent = (pct >= 0 ? '+' : '') + pct.toFixed(1) + '%';
        out.className = 'delta num ' + (pct < 0 ? 'down' : 'up');
      });
    });
  };
  refresh(document);
  document.addEventListener('input', e => {
    if (e.target.matches && e.target.matches('[data-ladder]')) refresh(e.target.closest('.ladder'));
  });
}

function initFilters() {
  const q = document.getElementById('q');
  if (!q) return;
  const rows = document.querySelectorAll('#rows tr');
  const counter = document.querySelector('.result-count');
  const run = () => {
    const text = q.value.trim().toLowerCase();
    const filter = (document.querySelector('.chip.on') || {}).dataset?.filter || 'all';
    let shown = 0;
    rows.forEach(tr => {
      const okText = !text || tr.textContent.toLowerCase().includes(text);
      const okFilter = filter === 'all' || tr.dataset.status === filter ||
        (filter === 'alarm' && tr.dataset.alarm === '1') ||
        (filter === 'long' && tr.dataset.long === '1') ||
        (filter === 'short' && tr.dataset.short === '1');
      const show = okText && okFilter;
      tr.classList.toggle('hidden', !show);
      if (show) shown++;
    });
    if (counter) counter.textContent = '共 ' + shown + ' 条';
  };
  q.addEventListener('input', run);
  document.querySelectorAll('.chip').forEach(c => c.addEventListener('click', () => {
    document.querySelectorAll('.chip').forEach(x => x.classList.remove('on'));
    c.classList.add('on');
    run();
  }));
}

document.addEventListener('DOMContentLoaded', () => {
  document.body.insertAdjacentHTML('afterbegin', SPRITE);
  initTheme();
  initTabs();
  initLadders();
  initFilters();
});
