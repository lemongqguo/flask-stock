/* ============================================================================
   股池监控台 · 前端交互（取代 Bootstrap/jQuery/main.js）
   依赖：无。图标为内联 SVG sprite（本文件注入），离线可用。
   ========================================================================== */

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
  <symbol id="i-chevron-left" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M11 17l-5-5 5-5"/><path d="M18 17l-5-5 5-5"/></symbol>
  <symbol id="i-chevron-right" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M13 17l5-5-5-5"/><path d="M6 17l5-5-5-5"/></symbol>
  <symbol id="i-cog" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-2.7 1.1V21a2 2 0 1 1-4 0v-.1A1.6 1.6 0 0 0 7.5 19.4l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1A1.6 1.6 0 0 0 3 14.9H3a2 2 0 1 1 0-4h.1A1.6 1.6 0 0 0 4.6 8.4l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1A1.6 1.6 0 0 0 10 4.5V4a2 2 0 1 1 4 0v.1a1.6 1.6 0 0 0 2.7 1.1l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1A1.6 1.6 0 0 0 21 11h.1a2 2 0 1 1 0 4H21a1.6 1.6 0 0 0-1.6 1Z"/></symbol>
  <symbol id="i-gauge" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 14 8 9"/><path d="M20.5 18a9.5 9.5 0 1 0-17 0"/><path d="M3.5 18h17"/></symbol>
  <symbol id="i-sparkles" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 3l1.8 4.7L18.5 9.5 13.8 11.3 12 16l-1.8-4.7L5.5 9.5l4.7-1.8Z"/><path d="M18 16.5l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8Z"/></symbol>
  <symbol id="i-mail" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/></symbol>
  <symbol id="i-lock" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="4" y="10" width="16" height="10" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></symbol>
  <symbol id="i-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="m4 12.5 5 5L20 6.5"/></symbol>
  <symbol id="i-send" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M21 3 3 10.5l7 3 3 7Z"/><path d="M21 3l-8 17"/></symbol>
  <symbol id="i-trend-down" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="m3 7 7 7 4-4 7 7"/><path d="M21 17v-6h-6"/></symbol>
  <symbol id="i-alert" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 3 2 20h20L12 3Z"/><path d="M12 9v5M12 17h.01"/></symbol>
  <symbol id="i-close" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 6l12 12M18 6 6 18"/></symbol>
  <symbol id="i-scale" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 4v16M8 20h8"/><path d="M5 8h14"/><path d="M3.5 13 5 8l1.5 5z"/><path d="M17.5 13 19 8l1.5 5z"/><path d="M3.5 13h3M17.5 13h3"/></symbol>
  <symbol id="i-candles" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M7 3v18M17 3v18"/><rect x="5" y="8" width="4" height="7" rx="1"/><rect x="15" y="5" width="4" height="9" rx="1"/></symbol>
  <symbol id="i-compare" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 20l6-6"/><path d="M4 20h5M4 20v-5"/><path d="M20 4l-6 6"/><path d="M20 4h-5M20 4v5"/></symbol>
  <symbol id="i-target" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4.5"/><circle cx="12" cy="12" r="1"/></symbol>
  <symbol id="i-shield" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6l8-3Z"/><path d="M12 9v4M12 16h.01"/></symbol>
</svg>`;

/* ---------------- 主题 ---------------- */
const THEME_KEY = 'stock-ui-theme';

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  const icon = document.querySelector('#theme-icon');
  if (icon) icon.setAttribute('href', theme === 'dark' ? '#i-moon' : '#i-sun');
  try { localStorage.setItem(THEME_KEY, theme); } catch (e) { /* 隐私模式下可能不可用 */ }
}

function initTheme() {
  applyTheme(document.documentElement.dataset.theme === 'light' ? 'light' : 'dark');
  document.querySelectorAll('[data-theme-toggle]').forEach(btn => {
    btn.addEventListener('click', () => {
      applyTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
    });
  });
}

/* ---------------- 页签（data-tabs 组内 .tab 切换 [data-body]） ---------------- */
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

/* ---------------- 三档阶梯：实时显示阈值距现价的百分比 ---------------- */
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

/* ---------------- 卖出价：动态显示距现价的涨跌幅（data-sell + data-sell-hint） ---------------- */
function initSellHint() {
  const input = document.querySelector('input[data-sell]');
  const hint = document.querySelector('[data-sell-hint]');
  if (!input || !hint) return;
  const cur = parseFloat((input.closest('form').querySelector('.ladder') || {}).dataset?.current);
  if (!isFinite(cur) || cur === 0) return;
  input.addEventListener('input', () => {
    const v = parseFloat(input.value);
    if (!isFinite(v)) { hint.textContent = '达到该价格触发卖出提醒'; return; }
    const gap = (v - cur) / cur * 100;
    hint.innerHTML = '现价 <b class="num">' + cur.toFixed(2) + '</b>，还需 <b class="num '
      + (gap >= 0 ? 'up' : 'down') + '">' + (gap >= 0 ? '+' : '') + gap.toFixed(1) + '%</b> 触发';
  });
}

/* ---------------- 告警设置：左侧标的列表选中 ---------------- */
function initStockPick() {
  document.querySelectorAll('[data-stock-item]').forEach(item => {
    item.addEventListener('click', () => {
      document.querySelectorAll('[data-stock-item]').forEach(x => x.classList.toggle('on', x === item));
      const id = item.dataset.stockItem;
      document.querySelectorAll('[data-stock-panel]').forEach(p => {
        p.classList.toggle('hidden', p.dataset.stockPanel !== id);
      });
    });
  });
}

/* ---------------- 搜索回车提交 ---------------- */
function initSearchEnter() {
  document.querySelectorAll('input[name="search"]').forEach(input => {
    input.addEventListener('keypress', event => {
      if (event.key === 'Enter') {
        event.preventDefault();
        const form = event.target.closest('form');
        if (form) form.submit();
      }
    });
  });
}

/* ---------------- 文本即时筛选 ----------------
   容器: <div data-text-filter="#list" data-text-empty="#empty">
   输入: <input data-text-input>
   行:   <a data-search="隆基绿能 sh601012">
   理由：列表已一次性渲染（≤ 200 行），本地过滤比每敲一个字就请求一次服务端快且不打断输入。 */
function initTextFilters() {
  document.querySelectorAll('[data-text-filter]').forEach(box => {
    const input = box.querySelector('[data-text-input]');
    const list = document.querySelector(box.dataset.textFilter);
    const empty = box.dataset.textEmpty ? document.querySelector(box.dataset.textEmpty) : null;
    if (!input || !list) return;

    const rows = Array.from(list.querySelectorAll('[data-search]'));
    function run() {
      const needle = input.value.trim().toLowerCase();
      let shown = 0;
      rows.forEach(row => {
        const hit = !needle || (row.dataset.search || '').includes(needle);
        row.style.display = hit ? '' : 'none';
        if (hit) shown += 1;
      });
      if (empty) empty.style.display = shown ? 'none' : '';
    }
    input.addEventListener('input', run);
    input.addEventListener('search', run);  // type=search 的清除按钮
    run();
  });
}

/* ---------------- 防重复提交 ---------------- */
function initSubmitOnce() {
  document.querySelectorAll('form[data-submit-once]').forEach(form => {
    form.addEventListener('submit', () => {
      const btn = form.querySelector('button[type="submit"], input[type="submit"]');
      if (btn) {
        // 圆形图标按钮（如 AI 追问的发送键）只禁用、不换文案，否则「提交中…」会撑破圆形
        const keepContent = btn.hasAttribute('data-keep-content');
        if (!keepContent) {
          btn.dataset.originalText = btn.innerHTML;
          btn.textContent = '提交中…';
        }
        btn.disabled = true;
        setTimeout(() => {
          if (!form.checkValidity()) {
            btn.disabled = false;
            if (!keepContent) btn.innerHTML = btn.dataset.originalText;
          }
        }, 800);
      }
    });
  });
}

/* ---------------- 每页条数切换跳转（select[data-perpage]） ---------------- */
function initPerPageSelect() {
  document.querySelectorAll('select[data-perpage]').forEach(sel => {
    sel.addEventListener('change', () => {
      const url = sel.options[sel.selectedIndex].value;
      if (url) window.location = url;
    });
  });
}

/* ---------------- chips 前端过滤（声明式，不发起请求） ----------------
   容器: <div data-chip-filter="status,alarm" data-chip-rows="#rows tr[data-status]" data-chip-count="#result-count" data-total="123">
   按钮: <button class="chip" data-filter="all|active|...">，行匹配 data-{key} === filter（任一 key 命中即可） */
function initChipFilters() {
  document.querySelectorAll('[data-chip-filter]').forEach(group => {
    const keys = group.dataset.chipFilter.split(',').map(s => s.trim());
    const rowsSelector = group.dataset.chipRows;
    const counter = group.dataset.chipCount ? document.querySelector(group.dataset.chipCount) : null;
    const total = group.dataset.total || '';
    function run() {
      const on = group.querySelector('.chip.on');
      const filter = on ? on.dataset.filter : 'all';
      let shown = 0;
      document.querySelectorAll(rowsSelector).forEach(tr => {
        const ok = filter === 'all' || keys.some(k => tr.dataset[k] === filter);
        tr.classList.toggle('hidden', !ok);
        if (ok) shown++;
      });
      if (counter) counter.textContent = '本页显示 ' + shown + ' 条' + (total ? ' / 共 ' + total + ' 条' : '');
    }
    group.querySelectorAll('.chip[data-filter]').forEach(c => {
      c.addEventListener('click', () => {
        group.querySelectorAll('.chip').forEach(x => x.classList.remove('on'));
        c.classList.add('on');
        run();
      });
    });
  });
}

/* ---------------- 登录/注册页签切换 ---------------- */
function initAuthTabs() {
  function show(tab) {
    document.querySelectorAll('[data-auth-tab]').forEach(t => {
      t.classList.toggle('on', t.dataset.authTab === tab);
    });
    document.querySelectorAll('[data-auth-panel]').forEach(p => {
      p.classList.toggle('hidden', p.dataset.authPanel !== tab);
    });
    const first = document.querySelector('[data-auth-panel="' + tab + '"] input');
    if (first) first.focus();
  }
  document.querySelectorAll('[data-auth-tab]').forEach(t => {
    t.addEventListener('click', () => show(t.dataset.authTab));
  });
  document.querySelectorAll('[data-auth-link]').forEach(a => {
    a.addEventListener('click', e => { e.preventDefault(); show(a.dataset.authLink); });
  });
}

/* ---------------- 告警通知开关（账户设置） ---------------- */
function initNotifyToggles() {
  document.querySelectorAll('.notify-toggle').forEach((label) => {
    const input = label.querySelector('input[type="checkbox"]');
    const status = label.querySelector('.status');
    if (!input || !status) return;
    const sync = () => status.classList.toggle('on', input.checked);
    input.addEventListener('change', sync);
    sync();  // 以 checkbox 为准，避免服务端渲染与提交值不一致
  });
}

/* ---------------- AI 追问 Composer ---------------- */
/* 交互契约（007）：
   1. Enter 发送、Shift+Enter 换行；输入框随内容长高（到 max-height 后内部滚动）；
   2. 「密钥」pill 展开/收起密钥面板——面板里的输入与测试按钮是同一个表单的 formaction，
      不额外发请求；未就绪时输入框禁用，但密钥入口必须一直可点（否则没法录密钥）。 */
function initAskComposer() {
  const box = document.querySelector('.ask-box');
  if (!box) return;

  const input = box.querySelector('.ask-input');
  if (input) {
    const grow = () => {
      input.style.height = 'auto';
      input.style.height = input.scrollHeight + 'px';
    };
    input.addEventListener('input', grow);
    grow();
    input.addEventListener('keydown', (event) => {
      if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return;
      event.preventDefault();
      if (!input.disabled) box.requestSubmit();
    });
  }

  const trigger = box.querySelector('[data-ask-key]');
  const panel = box.querySelector('[data-ask-key-panel]');
  if (trigger && panel) {
    trigger.addEventListener('click', () => {
      const open = panel.hasAttribute('hidden');
      panel.toggleAttribute('hidden', !open);
      trigger.setAttribute('aria-expanded', String(open));
      if (open) {
        const field = panel.querySelector('input[name="api_key"]');
        if (field) field.focus();
      }
    });
  }
}

/* ---------------- 密码强度条（纯视觉提示） ---------------- */
function initPwStrength() {
  const input = document.querySelector('input[name="new_password"]');
  const bar = document.querySelector('#pw-strength, [data-pw-strength]');
  if (!input || !bar) return;
  input.addEventListener('input', () => {
    const v = input.value;
    let score = 0;
    if (v.length >= 6) score += 34;
    if (v.length >= 10) score += 33;
    if (/[0-9]/.test(v) && /[a-zA-Z]/.test(v)) score += 33;
    bar.style.width = score + '%';
    bar.style.background = score > 66 ? 'var(--down)' : score > 33 ? 'var(--accent)' : 'var(--up)';
  });
}

/* ---------------- 侧栏折叠（data-side-toggle） ---------------- */
function initSideToggle() {
  const shell = document.querySelector('.shell');
  const btn = document.querySelector('[data-side-toggle]');
  if (!shell || !btn) return;

  const KEY = 'sidebar-collapsed';

  function apply(collapsed) {
    shell.classList.toggle('side-collapsed', collapsed);
    btn.setAttribute('aria-expanded', String(!collapsed));
    const label = collapsed ? '展开侧栏' : '折叠侧栏';
    btn.title = label;
    btn.setAttribute('aria-label', label);
    // 折叠后只剩图标，用 chevron 方向表示"点一下会往哪边走"
    btn.innerHTML = '<svg width="14" height="14"><use href="#'
      + (collapsed ? 'i-chevron-right' : 'i-chevron-left') + '"/></svg>';
  }

  apply(localStorage.getItem(KEY) === '1');

  btn.addEventListener('click', () => {
    const collapsed = !shell.classList.contains('side-collapsed');
    localStorage.setItem(KEY, collapsed ? '1' : '0');
    apply(collapsed);
  });
}

/* ---------------- 刷新行情（data-refresh-quotes） ---------------- */
function initRefreshQuotes() {
  const btn = document.querySelector('[data-refresh-quotes]');
  if (!btn) return;

  const label = btn.querySelector('[data-refresh-text]');
  const DEFAULT_TEXT = '刷新行情';

  // 表格列（data-col）→ 接口字段
  const FIELDS = { price: 'current_price', pe: 'current_pe', pb: 'current_pb' };

  function setCell(tr, col, value) {
    const td = tr.querySelector('[data-col="' + col + '"]');
    if (!td) return false;
    const next = (value === null || value === undefined) ? '—' : Number(value).toFixed(2);
    if (td.textContent.trim() === next) return false;

    td.textContent = next;
    // 值变了就闪一下：库里的数据常常和页面上已经显示的一样（监控线程刚采集过），
    // 不变时若没有别的反馈，点按钮看上去就是"没反应"
    td.classList.remove('flash');
    void td.offsetWidth;  // 强制回流，重新触发动画
    td.classList.add('flash');
    setTimeout(() => td.classList.remove('flash'), 1200);
    return true;
  }

  function reset(text) {
    if (label) label.textContent = text;
    btn.classList.remove('is-loading');
    setTimeout(() => {
      btn.disabled = false;
      if (label) label.textContent = DEFAULT_TEXT;
    }, 2200);
  }

  btn.addEventListener('click', () => {
    if (btn.disabled) return;

    // 只刷新当前页可见行：整表刷新既没必要，也会拖慢/触发限流
    const ids = Array.prototype.map.call(
      document.querySelectorAll('#rows tr[data-id]'), tr => tr.dataset.id);
    if (!ids.length) { reset('没有可刷新的行'); return; }

    btn.disabled = true;
    btn.classList.add('is-loading');
    if (label) label.textContent = '刷新中…';

    fetch(btn.dataset.refreshUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'fetch' },
      body: JSON.stringify({ ids: ids }),
    })
      .then(resp => (resp.ok ? resp.json() : null))
      .then(data => {
        if (!data) { reset('刷新失败'); return; }
        let rows = 0, changed = 0;
        (data.quotes || []).forEach(q => {
          const tr = document.querySelector('#rows tr[data-id="' + q.id + '"]');
          if (!tr) return;
          rows += 1;
          Object.keys(FIELDS).forEach(col => {
            if (setCell(tr, col, q[FIELDS[col]])) changed += 1;
          });
        });
        // 明确区分"有更新"和"本来就是最新的"——后者最容易被当成按钮没生效
        reset(changed
          ? '已刷新 ' + rows + ' 条 · ' + changed + ' 项更新'
          : '已是最新 ' + (data.updated_at || ''));
      })
      .catch(() => reset('刷新失败'));
  });
}

/* ---------------- 系统状态轮询（侧栏底部 / 顶栏徽标） ---------------- */
function initSystemStatus() {
  const root = document.querySelector('[data-system-status]');
  const pill = document.querySelector('[data-monitor-pill]');
  if (!root && !pill) return;

  const url = (root && root.dataset.statusUrl) || '/stock/api/system_status';
  const INTERVAL = 30000;

  function setText(selector, text) {
    const el = root && root.querySelector(selector);
    if (el && text !== undefined) el.textContent = text;
  }

  function apply(data) {
    if (!data) return;
    if (root) {
      setText('[data-status-monitor]', data.monitor && data.monitor.text);
      setText('[data-status-session]', data.session && data.session.text);
      setText('[data-status-cooldown]', data.cooldown && data.cooldown.text);
      setText('[data-status-xueqiu]', data.xueqiu && data.xueqiu.text);
      const mon = root.querySelector('[data-status-monitor]');
      if (mon && data.monitor) {
        mon.classList.toggle('down', !!data.monitor.running);
        mon.classList.toggle('muted', !data.monitor.running);
      }
      const xq = root.querySelector('[data-status-xueqiu]');
      if (xq && data.xueqiu) {
        xq.classList.toggle('down', !!data.xueqiu.ok);
        xq.classList.toggle('up', !data.xueqiu.ok);
      }
    }
    if (pill && data.monitor) {
      // 停止时去掉 live，呼吸点随之停止
      pill.classList.toggle('live', !!data.monitor.running);
      const text = pill.querySelector('[data-monitor-text]');
      if (text) text.textContent = data.monitor.running ? '监控运行中' : '监控已停止';
    }
  }

  function refresh() {
    // 页面在后台时不做无谓请求
    if (document.hidden) return;
    fetch(url, { headers: { 'X-Requested-With': 'fetch' } })
      .then(resp => (resp.ok ? resp.json() : null))
      .then(apply)
      .catch(() => { /* 网络异常保留上一次的值，不打断页面 */ });
  }

  setInterval(refresh, INTERVAL);
}

/* ---------------- 告警设置：?stock_id= 直达指定面板 ---------------- */
function initStockDeepLink() {
  const params = new URLSearchParams(window.location.search);
  const target = params.get('stock_id');
  if (!target) return;
  const item = document.querySelector('[data-stock-item="' + target + '"]');
  if (item) item.click();
}

/* ---------------- AI 页标的搜索（data-ai-search，服务端真查库） ---------------- */
function initAiSearch() {
  const box = document.querySelector('[data-ai-search]');
  if (!box) return;

  const input = box.querySelector('[data-ai-input]');
  const menu = box.querySelector('[data-ai-menu]');
  const clearBtn = box.querySelector('[data-ai-clear]');
  const url = box.dataset.url || '/stock/ai/api/search';
  const minLen = parseInt(box.dataset.min || '1', 10);
  if (!input || !menu) return;

  const DELAY = 220;
  let timer = null;
  let seq = 0;      // 请求序号：迟到的旧响应直接丢弃，避免覆盖新结果
  let items = [];
  let cursor = -1;

  function open() { menu.hidden = false; box.classList.add('is-open'); }
  function close() { menu.hidden = true; box.classList.remove('is-open'); cursor = -1; }

  function state(text, tone) {
    menu.innerHTML = '<div class="ai-combo-state' + (tone ? ' ' + tone : '') + '">' + text + '</div>';
    open();
  }

  function esc(s) {
    return String(s === undefined || s === null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function render(list, truncated) {
    items = list || [];
    cursor = -1;
    if (!items.length) { state('没有匹配的标的，换个名称或代码试试'); return; }
    menu.innerHTML = items.map((it, i) =>
      '<a class="ai-opt" href="' + esc(it.url) + '" data-idx="' + i + '">'
      + '<span class="ai-opt-avatar">' + esc((it.name || '?').slice(0, 1)) + '</span>'
      + '<span class="ai-opt-main"><span class="ai-opt-name">' + esc(it.name) + '</span>'
      + '<span class="ai-opt-code num">' + esc(it.code) + '</span></span>'
      + '<span class="ai-opt-price num' + (it.price === null ? ' muted' : '') + '">'
      + (it.price === null ? '—' : Number(it.price).toFixed(2)) + '</span></a>').join('')
      + (truncated ? '<div class="ai-combo-state">只显示前 ' + items.length + ' 条，请输入更完整的关键字</div>' : '');
    open();
  }

  function move(step) {
    const opts = menu.querySelectorAll('.ai-opt');
    if (!opts.length) return;
    cursor = (cursor + step + opts.length) % opts.length;
    opts.forEach((el, i) => el.classList.toggle('on', i === cursor));
    opts[cursor].scrollIntoView({ block: 'nearest' });
  }

  function run() {
    const q = input.value.trim();
    if (clearBtn) clearBtn.hidden = !q;
    if (q.length < minLen) { close(); return; }

    const mine = ++seq;
    state('搜索中…');
    fetch(url + '?q=' + encodeURIComponent(q), { headers: { 'X-Requested-With': 'fetch' } })
      .then(resp => (resp.ok ? resp.json() : Promise.reject(new Error('HTTP ' + resp.status))))
      .then(data => { if (mine === seq) render(data.items, data.truncated); })
      .catch(() => { if (mine === seq) state('搜索失败，请稍后重试', 'warn'); });
  }

  input.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(run, DELAY);
  });
  input.addEventListener('focus', () => { if (input.value.trim().length >= minLen) run(); });
  input.addEventListener('keydown', e => {
    if (e.key === 'ArrowDown') { e.preventDefault(); if (!menu.hidden) move(1); else run(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); move(-1); }
    else if (e.key === 'Enter') {
      const target = menu.querySelector('.ai-opt.on') || menu.querySelector('.ai-opt');
      if (target) { e.preventDefault(); window.location.href = target.getAttribute('href'); }
    } else if (e.key === 'Escape') { close(); input.blur(); }
  });

  if (clearBtn) {
    clearBtn.addEventListener('click', () => {
      input.value = '';
      clearBtn.hidden = true;
      close();
      input.focus();
    });
  }

  // 点击别处收起：下拉是浮层，不收起会一直盖在内容上
  document.addEventListener('click', e => { if (!box.contains(e.target)) close(); });
}

/* ---------------- AI 页「换个标的」：回到顶部搜索框 ---------------- */
function initAiFocusSearch() {
  document.querySelectorAll('[data-ai-focus]').forEach(btn => {
    btn.addEventListener('click', () => {
      const input = document.querySelector('[data-ai-input]');
      if (!input) return;
      const hero = document.querySelector('.ai-hero');
      if (hero) hero.scrollIntoView({ behavior: 'smooth', block: 'start' });
      input.focus();
      input.select();
    });
  });
}

document.addEventListener('DOMContentLoaded', () => {
  document.body.insertAdjacentHTML('afterbegin', SPRITE);
  initTheme();
  initSideToggle();
  initSystemStatus();
  initRefreshQuotes();
  initTabs();
  initLadders();
  initSellHint();
  initStockPick();
  initSearchEnter();
  initSubmitOnce();
  initPerPageSelect();
  initChipFilters();
  initTextFilters();
  initAuthTabs();
  initPwStrength();
  initNotifyToggles();
  initStockDeepLink();
  initAiSearch();
  initAiFocusSearch();
  initAskComposer();
});
