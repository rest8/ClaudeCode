/**
 * World Monitor - Dashboard Module
 * Manages UI, data fetching, and panel interactions.
 */

const Dashboard = (() => {
    const REFRESH_INTERVAL = 180000; // 3 min
    let alertsOnly = false;

    function init() {
        WorldMap.init();
        setupClock();
        setupTabs();
        setupButtons();
        loadAllData();

        // Auto-refresh
        setInterval(loadAllData, REFRESH_INTERVAL);
    }

    // ---- Clock ----
    function setupClock() {
        function update() {
            const now = new Date();
            const utc = now.toISOString().replace('T', ' ').substring(0, 19) + ' UTC';
            document.getElementById('clock').textContent = utc;
        }
        update();
        setInterval(update, 1000);
    }

    // ---- Tabs ----
    function setupTabs() {
        document.querySelectorAll('.tab').forEach(tab => {
            tab.addEventListener('click', () => {
                document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
                document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
                tab.classList.add('active');
                document.getElementById('panel-' + tab.dataset.tab).classList.add('active');
            });
        });
    }

    // ---- Buttons ----
    function setupButtons() {
        document.getElementById('btn-refresh').addEventListener('click', () => {
            loadAllData();
        });

        document.getElementById('btn-alerts').addEventListener('click', (e) => {
            alertsOnly = !alertsOnly;
            e.target.classList.toggle('active');
            loadNews();
        });

        document.getElementById('btn-layers').addEventListener('click', () => {
            document.getElementById('layers-panel').classList.toggle('hidden');
        });

        document.getElementById('news-source-filter').addEventListener('change', () => {
            loadNews();
        });
    }

    // ---- Data loading ----
    function loadAllData() {
        updateStatus('Refreshing...');
        Promise.all([
            loadNews(),
            loadEarthquakes(),
            loadConflictZones(),
            loadHotspots(),
            loadGdelt(),
            loadStats(),
        ]).then(() => {
            updateStatus('Live');
            document.querySelector('.dot').classList.add('connected');
        }).catch(() => {
            updateStatus('Error');
        });
    }

    function updateStatus(text) {
        document.getElementById('status-text').textContent = text;
    }

    // ---- News ----
    function loadNews() {
        const source = document.getElementById('news-source-filter').value;
        let url = '/api/news?limit=200';
        if (source) url += '&source=' + encodeURIComponent(source);
        if (alertsOnly) url += '&alerts=true';

        return fetch(url)
            .then(r => r.json())
            .then(data => {
                renderNews(data);
                renderAlerts(data.filter(d => d.is_alert));
                renderTicker(data);
                updateSourceFilter(data);
                document.getElementById('stat-news').textContent = data.length;
            })
            .catch(err => {
                console.error('News fetch failed:', err);
                document.getElementById('news-list').innerHTML = '<div class="loading">Failed to load news</div>';
            });
    }

    function renderNews(items) {
        const container = document.getElementById('news-list');
        if (!items.length) {
            container.innerHTML = '<div class="loading">No news available</div>';
            return;
        }
        container.innerHTML = items.slice(0, 100).map(item => `
            <div class="news-item ${item.is_alert ? 'alert' : ''}" onclick="window.open('${escapeHtml(item.link)}', '_blank')">
                <div class="news-source">${escapeHtml(item.source)}</div>
                <div class="news-title">${escapeHtml(item.title)}</div>
                <div class="news-time">${formatTime(item.published)}</div>
                ${item.summary ? `<div class="news-summary">${escapeHtml(item.summary)}</div>` : ''}
            </div>
        `).join('');
    }

    function renderAlerts(items) {
        const container = document.getElementById('alerts-list');
        if (!items.length) {
            container.innerHTML = '<div class="loading">No active alerts</div>';
            return;
        }
        container.innerHTML = items.map(item => `
            <div class="news-item alert" onclick="window.open('${escapeHtml(item.link)}', '_blank')">
                <div class="news-source">${escapeHtml(item.source)}</div>
                <div class="news-title">${escapeHtml(item.title)}</div>
                <div class="news-time">${formatTime(item.published)}</div>
            </div>
        `).join('');
    }

    function renderTicker(items) {
        const ticker = document.getElementById('ticker-content');
        const alertItems = items.filter(i => i.is_alert).slice(0, 10);
        const regularItems = items.slice(0, 15);
        const all = [...alertItems, ...regularItems];
        ticker.innerHTML = all.map(item => {
            const cls = item.is_alert ? 'ticker-alert' : '';
            return `<span class="${cls}">${escapeHtml(item.title)}</span><span class="ticker-sep">|</span>`;
        }).join('');
    }

    function updateSourceFilter(items) {
        const select = document.getElementById('news-source-filter');
        const current = select.value;
        const sources = [...new Set(items.map(i => i.source))].sort();
        const options = '<option value="">All Sources</option>' +
            sources.map(s => `<option value="${escapeHtml(s)}" ${s === current ? 'selected' : ''}>${escapeHtml(s)}</option>`).join('');
        select.innerHTML = options;
    }

    // ---- Earthquakes ----
    function loadEarthquakes() {
        return fetch('/api/earthquakes')
            .then(r => r.json())
            .then(data => {
                WorldMap.updateEarthquakes(data);
                document.getElementById('stat-earthquakes').textContent = data.length;
            })
            .catch(err => console.error('Earthquake fetch failed:', err));
    }

    // ---- Conflict Zones ----
    function loadConflictZones() {
        return fetch('/api/layers/conflict-zones')
            .then(r => r.json())
            .then(data => WorldMap.updateConflictZones(data))
            .catch(err => console.error('Conflict zone fetch failed:', err));
    }

    // ---- Hotspots ----
    function loadHotspots() {
        return fetch('/api/layers/hotspots')
            .then(r => r.json())
            .then(data => WorldMap.updateHotspots(data))
            .catch(err => console.error('Hotspot fetch failed:', err));
    }

    // ---- GDELT ----
    function loadGdelt() {
        return fetch('/api/gdelt')
            .then(r => r.json())
            .then(data => {
                renderGdelt(data);
            })
            .catch(err => {
                console.error('GDELT fetch failed:', err);
                document.getElementById('gdelt-list').innerHTML = '<div class="loading">Failed to load GDELT data</div>';
            });
    }

    function renderGdelt(items) {
        const container = document.getElementById('gdelt-list');
        if (!items.length) {
            container.innerHTML = '<div class="loading">No GDELT data available</div>';
            return;
        }
        container.innerHTML = items.slice(0, 50).map(item => `
            <div class="gdelt-item" onclick="window.open('${escapeHtml(item.url)}', '_blank')">
                <div class="gdelt-source">${escapeHtml(item.source || '')}</div>
                <div class="gdelt-title">${escapeHtml(item.title)}</div>
            </div>
        `).join('');
    }

    // ---- Stats ----
    function loadStats() {
        return Promise.all([
            fetch('/api/conflicts').then(r => r.json()).then(data => {
                document.getElementById('stat-conflicts').textContent = data.length;
            }).catch(() => {}),
            fetch('/api/disasters').then(r => r.json()).then(data => {
                document.getElementById('stat-disasters').textContent = data.length;
            }).catch(() => {}),
        ]);
    }

    // ---- Helpers ----
    function escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function formatTime(isoStr) {
        if (!isoStr) return '';
        try {
            const date = new Date(isoStr);
            const now = new Date();
            const diffMs = now - date;
            const diffMin = Math.floor(diffMs / 60000);
            if (diffMin < 1) return 'Just now';
            if (diffMin < 60) return `${diffMin}m ago`;
            const diffHr = Math.floor(diffMin / 60);
            if (diffHr < 24) return `${diffHr}h ago`;
            const diffDay = Math.floor(diffHr / 24);
            return `${diffDay}d ago`;
        } catch {
            return isoStr;
        }
    }

    return { init };
})();

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', Dashboard.init);
