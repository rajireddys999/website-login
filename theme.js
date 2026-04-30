// Apply saved theme to <html> before first paint — prevents flash of wrong theme
(function() {
  if (localStorage.getItem('la_theme') === 'dark') {
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

  // Inject desktop/mobile switcher button
  var isDesktopMode = localStorage.getItem('la_viewport') === 'desktop';
  var btn = document.createElement('button');
  btn.id = 'viewport-toggle-btn';
  btn.innerHTML = isDesktopMode
    ? '<span style="font-size:13px">📱</span><span>Mobile</span>'
    : '<span style="font-size:13px">🖥️</span><span>Desktop</span>';
  btn.title = isDesktopMode ? 'Switch to Mobile View' : 'Switch to Desktop View';
  btn.style.cssText = [
    'position:fixed',
    'bottom:20px',
    'right:16px',
    'z-index:10000',
    'display:flex',
    'align-items:center',
    'gap:5px',
    'background:linear-gradient(135deg,rgba(30,20,60,0.88),rgba(60,30,90,0.88))',
    'color:#e2d9f3',
    'font-size:11px',
    'font-weight:700',
    'letter-spacing:.5px',
    'padding:6px 13px 6px 10px',
    'border-radius:30px',
    'border:1px solid rgba(180,140,255,0.25)',
    'cursor:pointer',
    'backdrop-filter:blur(10px)',
    'font-family:inherit',
    'white-space:nowrap',
    'box-shadow:0 4px 16px rgba(100,60,200,0.3),0 0 0 1px rgba(255,255,255,0.06) inset',
    'transition:all .2s',
    'opacity:.85'
  ].join(';');
  btn.addEventListener('mouseenter', function() {
    btn.style.opacity = '1';
    btn.style.transform = 'scale(1.05)';
    btn.style.boxShadow = '0 6px 20px rgba(100,60,200,0.45),0 0 0 1px rgba(255,255,255,0.1) inset';
  });
  btn.addEventListener('mouseleave', function() {
    btn.style.opacity = '.85';
    btn.style.transform = 'scale(1)';
    btn.style.boxShadow = '0 4px 16px rgba(100,60,200,0.3),0 0 0 1px rgba(255,255,255,0.06) inset';
  });
  btn.addEventListener('click', function() {
    var next = isDesktopMode ? 'mobile' : 'desktop';
    localStorage.setItem('la_viewport', next);
    location.reload();
  });
  document.body.appendChild(btn);
});
