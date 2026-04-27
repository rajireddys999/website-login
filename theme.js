// Apply saved theme to <html> before first paint — prevents flash of wrong theme
(function() {
  if (localStorage.getItem('la_theme') === 'dark') {
    document.documentElement.classList.add('dark');
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
});
