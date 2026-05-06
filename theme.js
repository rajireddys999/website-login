// Apply saved theme — dark is the default unless user explicitly chose light
(function() {
  if (localStorage.getItem('la_theme') !== 'light') {
    document.documentElement.classList.add('dark');
  }
})();

// Apply saved viewport mode before first paint
(function() {
  if (localStorage.getItem('la_viewport') === 'desktop') {
    var vp = document.querySelector('meta[name="viewport"]');
    if (vp) vp.setAttribute('content', 'width=1200');
  }
})();

function toggleTheme() {
  var isDark = document.documentElement.classList.toggle('dark');
  document.querySelectorAll('.theme-icon').forEach(function(el) {
    el.textContent = isDark ? '☀️' : '🌙';
  });
  localStorage.setItem('la_theme', isDark ? 'dark' : 'light');
}

document.addEventListener('DOMContentLoaded', function() {
  var isDark = document.documentElement.classList.contains('dark');
  document.querySelectorAll('.theme-icon').forEach(function(el) {
    el.textContent = isDark ? '☀️' : '🌙';
  });

  // ── Viewport Switcher (main page only) ──────────────────────────
  var _path = window.location.pathname;
  if (_path !== '/' && _path !== '/index.html' && !_path.endsWith('/index.html')) return;
  var isDesktop = localStorage.getItem('la_viewport') === 'desktop';

  var DESK_ICON = '<svg width="17" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>';
  var MOB_ICON  = '<svg width="12" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="2" width="14" height="20" rx="2"/><circle cx="12" cy="18" r="1.2" fill="currentColor" stroke="none"/></svg>';

  var wrap = document.createElement('div');
  wrap.id  = 'vp-switcher';
  wrap.style.cssText = [
    'position:fixed',
    'bottom:24px',
    'left:16px',
    'z-index:10000',
    'background:rgba(8,6,28,0.82)',
    'border:1px solid rgba(99,102,241,0.28)',
    'border-radius:18px',
    'backdrop-filter:blur(20px)',
    '-webkit-backdrop-filter:blur(20px)',
    'padding:10px 11px 11px',
    'box-shadow:0 8px 40px rgba(0,0,0,0.55),0 0 0 1px rgba(255,255,255,0.05) inset,0 0 60px rgba(99,102,241,0.07)',
    'font-family:-apple-system,BlinkMacSystemFont,Inter,sans-serif',
    'user-select:none',
  ].join(';');

  var ON  = 'background:linear-gradient(135deg,#6366f1,#7c3aed);color:#fff;box-shadow:0 3px 14px rgba(99,102,241,0.45)';
  var OFF = 'background:rgba(255,255,255,0.04);color:rgba(180,165,255,0.45);box-shadow:none';
  var BTN = [
    'display:flex','flex-direction:column','align-items:center','gap:5px',
    'padding:9px 16px','border-radius:12px','border:none','cursor:pointer',
    'font-size:9px','font-weight:700','letter-spacing:.7px','text-transform:uppercase',
    'transition:all .22s cubic-bezier(.4,0,.2,1)','font-family:inherit','min-width:58px',
    'line-height:1',
  ].join(';');

  wrap.innerHTML =
    '<div style="font-size:8px;font-weight:800;letter-spacing:2px;color:rgba(148,130,255,0.45);text-transform:uppercase;text-align:center;margin-bottom:8px">View As</div>' +
    '<div style="display:flex;gap:5px">' +
      '<button id="vp-desk" style="' + BTN + ';' + (isDesktop  ? ON : OFF) + '">' + DESK_ICON + '<span>Desktop</span></button>' +
      '<button id="vp-mob"  style="' + BTN + ';' + (!isDesktop ? ON : OFF) + '">' + MOB_ICON  + '<span>Mobile</span></button>'  +
    '</div>';

  document.body.appendChild(wrap);

  function wireBtn(id, mode, active) {
    var el = document.getElementById(id);
    el.addEventListener('click', function() {
      localStorage.setItem('la_viewport', mode);
      location.reload();
    });
    el.addEventListener('mouseenter', function() {
      if (active) {
        el.style.transform = 'scale(1.04)';
      } else {
        el.style.background = 'rgba(99,102,241,0.14)';
        el.style.color       = 'rgba(200,185,255,0.8)';
      }
    });
    el.addEventListener('mouseleave', function() {
      el.style.transform = '';
      if (!active) {
        el.style.background = 'rgba(255,255,255,0.04)';
        el.style.color       = 'rgba(180,165,255,0.45)';
      }
    });
  }

  wireBtn('vp-desk', 'desktop',  isDesktop);
  wireBtn('vp-mob',  'mobile',  !isDesktop);
});
