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
  btn.textContent = isDesktopMode ? '📱 Mobile Site' : '🖥️ Desktop Site';
  btn.style.cssText = [
    'position:fixed',
    'bottom:88px',
    'left:50%',
    'transform:translateX(-50%)',
    'z-index:9998',
    'background:rgba(15,15,15,0.72)',
    'color:#fff',
    'font-size:11px',
    'font-weight:600',
    'letter-spacing:.4px',
    'padding:5px 16px',
    'border-radius:20px',
    'border:1px solid rgba(255,255,255,.18)',
    'cursor:pointer',
    'backdrop-filter:blur(6px)',
    'font-family:inherit',
    'white-space:nowrap',
    'box-shadow:0 2px 10px rgba(0,0,0,.25)',
    'transition:opacity .2s'
  ].join(';');
  btn.addEventListener('mouseenter', function() { btn.style.opacity = '1'; });
  btn.addEventListener('mouseleave', function() { btn.style.opacity = '.75'; });
  btn.style.opacity = '.75';
  btn.addEventListener('click', function() {
    var next = isDesktopMode ? 'mobile' : 'desktop';
    localStorage.setItem('la_viewport', next);
    location.reload();
  });
  document.body.appendChild(btn);
});
