/* WellNest Service Worker for Android & Desktop System Push Notifications */

self.addEventListener('install', (event) => {
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    event.waitUntil(self.clients.claim());
});

self.addEventListener('push', (event) => {
    let data = { title: 'WellNest Clinical Alert', body: 'New clinical update received.' };
    if (event.data) {
        try {
            data = event.data.json();
        } catch (e) {
            data.body = event.data.text();
        }
    }
    const options = {
        body: data.body || 'New health trace update',
        icon: data.icon || 'https://i.ibb.co/DHkjd9VB/Well-Nest-Logo.png',
        badge: data.badge || 'https://i.ibb.co/DHkjd9VB/Well-Nest-Logo.png',
        vibrate: [200, 100, 200, 100, 200],
        tag: data.tag || 'wellnest-alert-' + Date.now(),
        renotify: true,
        data: { url: data.url || '/' }
    };
    event.waitUntil(self.registration.showNotification(data.title || 'WellNest Alert', options));
});

self.addEventListener('notificationclick', (event) => {
    event.notification.close();
    event.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
            for (const client of clientList) {
                if ('focus' in client) return client.focus();
            }
            if (clients.openWindow) {
                return clients.openWindow(event.notification.data?.url || '/');
            }
        })
    );
});
