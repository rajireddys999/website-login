const CACHE = 'laxmi-academy-v8';

const PRECACHE = [
  '/',
  '/index.html',
  '/login.html',
  '/signup.html',
  '/verify-email.html',
  '/forgot-password.html',
  '/reset-password.html',
  '/dashboard.html',
  '/instructor-dashboard.html',
  '/admin-dashboard.html',
  '/mission-control.html',
  '/privacy.html',
  '/terms.html',
  '/refund.html',
  '/offline.html',
  '/theme.css',
  '/theme.js',
  '/manifest.json',
  '/logo.png.jpeg'
];

// Install — pre-cache all static pages
self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(PRECACHE)).then(() => self.skipWaiting())
  );
});

// Activate — clear old caches
self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// Fetch — cache-first for static assets, network-first for API
self.addEventListener('fetch', e => {
  const { request } = e;
  const url = new URL(request.url);

  // Skip non-GET and API calls
  if (request.method !== 'GET' || url.pathname.startsWith('/api/')) return;

  e.respondWith(
    caches.match(request).then(cached => {
      const fresh = fetch(request).then(res => {
        if (res.ok) {
          caches.open(CACHE).then(c => c.put(request, res.clone()));
        }
        return res;
      }).catch(() => cached); // offline fallback to cache
      return cached || fresh.catch(() => caches.match('/offline.html'));
    })
  );
});
