/**
 * World Monitor - Map Module
 * Manages Leaflet map, layers, and data overlays.
 */

const WorldMap = (() => {
    let map;
    const layers = {};
    const layerGroups = {};

    // Custom icons
    const icons = {
        earthquake: (mag) => {
            const size = Math.max(8, mag * 4);
            const color = mag >= 5 ? '#ff4444' : '#ff8800';
            return L.divIcon({
                className: 'custom-marker',
                html: `<div style="width:${size}px;height:${size}px;background:${color};border-radius:50%;border:2px solid rgba(255,255,255,0.5);box-shadow:0 0 ${size}px ${color}80;"></div>`,
                iconSize: [size, size],
                iconAnchor: [size / 2, size / 2],
            });
        },
        hotspot: (level) => {
            const colors = { high: '#ff4444', medium: '#ff8800', low: '#ffcc00' };
            const color = colors[level] || '#ffcc00';
            return L.divIcon({
                className: 'custom-marker',
                html: `<div style="width:14px;height:14px;background:${color};border-radius:50%;border:2px solid rgba(255,255,255,0.6);box-shadow:0 0 10px ${color}80;animation:pulse 2s infinite;"></div>`,
                iconSize: [14, 14],
                iconAnchor: [7, 7],
            });
        },
        base: (operator) => {
            const colors = {
                'US': '#3b82f6', 'US/NATO': '#3b82f6', 'US/UK': '#3b82f6',
                'Russia': '#ef4444',
                'China': '#f97316',
                'France': '#818cf8',
                'UK': '#6366f1',
            };
            const color = colors[operator] || '#94a3b8';
            return L.divIcon({
                className: 'custom-marker',
                html: `<div style="width:8px;height:8px;background:${color};border:1.5px solid rgba(255,255,255,0.7);transform:rotate(45deg);"></div>`,
                iconSize: [8, 8],
                iconAnchor: [4, 4],
            });
        },
        nuclear: () => L.divIcon({
            className: 'custom-marker',
            html: '<div style="width:10px;height:10px;background:#eab308;border-radius:50%;border:2px solid #fef08a;box-shadow:0 0 8px #eab30880;"></div>',
            iconSize: [10, 10],
            iconAnchor: [5, 5],
        }),
        waterway: () => L.divIcon({
            className: 'custom-marker',
            html: '<div style="width:10px;height:10px;background:#06b6d4;border-radius:2px;border:2px solid rgba(255,255,255,0.6);"></div>',
            iconSize: [10, 10],
            iconAnchor: [5, 5],
        }),
        disaster: (category) => {
            const colors = { 'Wildfires': '#ff6600', 'Volcanoes': '#cc3300', 'Severe Storms': '#6644ff', 'Floods': '#2288ff' };
            const color = colors[category] || '#ff8800';
            return L.divIcon({
                className: 'custom-marker',
                html: `<div style="width:10px;height:10px;background:${color};border-radius:50%;border:2px solid rgba(255,255,255,0.5);box-shadow:0 0 8px ${color}80;"></div>`,
                iconSize: [10, 10],
                iconAnchor: [5, 5],
            });
        },
        conflict_event: () => L.divIcon({
            className: 'custom-marker',
            html: '<div style="width:8px;height:8px;background:#ef4444;border-radius:50%;border:1.5px solid rgba(255,200,200,0.7);box-shadow:0 0 6px #ef444480;"></div>',
            iconSize: [8, 8],
            iconAnchor: [4, 4],
        }),
    };

    function init() {
        map = L.map('map', {
            center: [25, 30],
            zoom: 3,
            minZoom: 2,
            maxZoom: 12,
            zoomControl: true,
            attributionControl: true,
        });

        // Dark map tiles (CartoDB Dark Matter)
        L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>',
            subdomains: 'abcd',
            maxZoom: 19,
        }).addTo(map);

        // Initialize layer groups
        const layerNames = [
            'earthquakes', 'conflicts', 'hotspots', 'bases',
            'nuclear', 'waterways', 'cables', 'disasters', 'conflict-events'
        ];
        layerNames.forEach(name => {
            layerGroups[name] = L.layerGroup();
        });

        // Add default layers
        layerGroups['earthquakes'].addTo(map);
        layerGroups['conflicts'].addTo(map);
        layerGroups['hotspots'].addTo(map);

        // Setup layer toggle handlers
        setupLayerToggles();

        return map;
    }

    function setupLayerToggles() {
        const mapping = {
            'layer-earthquakes': 'earthquakes',
            'layer-conflicts': 'conflicts',
            'layer-hotspots': 'hotspots',
            'layer-bases': 'bases',
            'layer-nuclear': 'nuclear',
            'layer-waterways': 'waterways',
            'layer-cables': 'cables',
            'layer-disasters': 'disasters',
            'layer-conflict-events': 'conflict-events',
        };

        Object.entries(mapping).forEach(([checkboxId, layerName]) => {
            const cb = document.getElementById(checkboxId);
            if (!cb) return;
            cb.addEventListener('change', () => {
                if (cb.checked) {
                    layerGroups[layerName].addTo(map);
                    // Fetch data if layer group is empty
                    if (layerGroups[layerName].getLayers().length === 0) {
                        loadLayerData(layerName);
                    }
                } else {
                    map.removeLayer(layerGroups[layerName]);
                }
            });
        });
    }

    function loadLayerData(name) {
        const urls = {
            'bases': '/api/layers/military-bases',
            'nuclear': '/api/layers/nuclear',
            'waterways': '/api/layers/waterways',
            'cables': '/api/layers/cables',
            'disasters': '/api/disasters',
            'conflict-events': '/api/conflicts',
        };
        if (urls[name]) {
            fetch(urls[name])
                .then(r => r.json())
                .then(data => {
                    if (name === 'bases') updateBases(data);
                    else if (name === 'nuclear') updateNuclear(data);
                    else if (name === 'waterways') updateWaterways(data);
                    else if (name === 'cables') updateCables(data);
                    else if (name === 'disasters') updateDisasters(data);
                    else if (name === 'conflict-events') updateConflictEvents(data);
                });
        }
    }

    function updateEarthquakes(data) {
        layerGroups['earthquakes'].clearLayers();
        data.forEach(eq => {
            const marker = L.marker([eq.lat, eq.lng], {
                icon: icons.earthquake(eq.magnitude),
            });
            marker.bindPopup(`
                <h4>M${eq.magnitude.toFixed(1)} Earthquake</h4>
                <div class="popup-detail">${eq.place}</div>
                <div class="popup-detail">Depth: ${eq.depth.toFixed(1)} km</div>
                ${eq.tsunami ? '<div class="popup-type">TSUNAMI WARNING</div>' : ''}
                ${eq.felt ? `<div class="popup-detail">Felt by ${eq.felt} people</div>` : ''}
            `);
            layerGroups['earthquakes'].addLayer(marker);
        });
    }

    function updateConflictZones(data) {
        layerGroups['conflicts'].clearLayers();
        data.forEach(zone => {
            const circle = L.circle([zone.lat, zone.lng], {
                radius: zone.radius,
                color: zone.color,
                fillColor: zone.color,
                fillOpacity: 0.1,
                weight: 1.5,
                dashArray: '5, 5',
            });
            circle.bindPopup(`
                <h4>${zone.name}</h4>
                <div class="popup-type">${zone.status}</div>
                <div class="popup-detail">${zone.description}</div>
            `);
            layerGroups['conflicts'].addLayer(circle);
        });
    }

    function updateHotspots(data) {
        layerGroups['hotspots'].clearLayers();
        data.forEach(hs => {
            const marker = L.marker([hs.lat, hs.lng], {
                icon: icons.hotspot(hs.level),
            });
            marker.bindPopup(`
                <h4>${hs.name}</h4>
                <div class="popup-type">${hs.level.toUpperCase()} RISK</div>
                <div class="popup-detail">${hs.description}</div>
            `);
            layerGroups['hotspots'].addLayer(marker);
        });
    }

    function updateBases(data) {
        layerGroups['bases'].clearLayers();
        data.forEach(base => {
            const marker = L.marker([base.lat, base.lng], {
                icon: icons.base(base.operator),
            });
            marker.bindPopup(`
                <h4>${base.name}</h4>
                <div class="popup-type">${base.operator} - ${base.type}</div>
            `);
            layerGroups['bases'].addLayer(marker);
        });
    }

    function updateNuclear(data) {
        layerGroups['nuclear'].clearLayers();
        data.forEach(fac => {
            const marker = L.marker([fac.lat, fac.lng], {
                icon: icons.nuclear(),
            });
            marker.bindPopup(`
                <h4>${fac.name}</h4>
                <div class="popup-type">${fac.type}</div>
                <div class="popup-detail">${fac.country}</div>
            `);
            layerGroups['nuclear'].addLayer(marker);
        });
    }

    function updateWaterways(data) {
        layerGroups['waterways'].clearLayers();
        data.forEach(ww => {
            const marker = L.marker([ww.lat, ww.lng], {
                icon: icons.waterway(),
            });
            marker.bindPopup(`
                <h4>${ww.name}</h4>
                <div class="popup-detail">Traffic: ${ww.traffic}</div>
                <div class="popup-detail">Controlled by: ${ww.controlled_by}</div>
            `);
            layerGroups['waterways'].addLayer(marker);
        });
    }

    function updateCables(data) {
        layerGroups['cables'].clearLayers();
        data.forEach(cable => {
            if (cable.points && cable.points.length >= 2) {
                const latlngs = cable.points.map(p => [p[0], p[1]]);
                const line = L.polyline(latlngs, {
                    color: '#06b6d4',
                    weight: 1.5,
                    opacity: 0.6,
                    dashArray: '4, 4',
                });
                line.bindPopup(`
                    <h4>${cable.name}</h4>
                    <div class="popup-detail">Capacity: ${cable.capacity}</div>
                    <div class="popup-detail">Route: ${cable.route}</div>
                `);
                layerGroups['cables'].addLayer(line);
            }
        });
    }

    function updateDisasters(data) {
        layerGroups['disasters'].clearLayers();
        data.forEach(d => {
            if (d.lat === 0 && d.lng === 0) return;
            const marker = L.marker([d.lat, d.lng], {
                icon: icons.disaster(d.category),
            });
            marker.bindPopup(`
                <h4>${d.title}</h4>
                <div class="popup-type">${d.category} ${d.alert_level ? '- ' + d.alert_level : ''}</div>
                <div class="popup-detail">Source: ${d.source}</div>
            `);
            layerGroups['disasters'].addLayer(marker);
        });
    }

    function updateConflictEvents(data) {
        layerGroups['conflict-events'].clearLayers();
        const cluster = L.markerClusterGroup({
            maxClusterRadius: 40,
            iconCreateFunction: (cluster) => {
                const count = cluster.getChildCount();
                return L.divIcon({
                    html: `<div style="background:#ef4444;color:white;border-radius:50%;width:24px;height:24px;display:flex;align-items:center;justify-content:center;font-size:10px;font-weight:bold;border:2px solid rgba(255,255,255,0.5);">${count}</div>`,
                    className: 'custom-cluster',
                    iconSize: [24, 24],
                });
            },
        });
        data.forEach(ev => {
            if (!ev.lat || !ev.lng) return;
            const marker = L.marker([ev.lat, ev.lng], {
                icon: icons.conflict_event(),
            });
            marker.bindPopup(`
                <h4>${ev.type || 'Conflict Event'}</h4>
                <div class="popup-type">${ev.sub_type || ev.notes || ''}</div>
                <div class="popup-detail">${ev.country || ''} ${ev.region ? '- ' + ev.region : ''}</div>
                <div class="popup-detail">Date: ${ev.date || ''}</div>
                ${ev.fatalities ? `<div class="popup-detail">Fatalities: ${ev.fatalities}</div>` : ''}
            `);
            cluster.addLayer(marker);
        });
        layerGroups['conflict-events'].addLayer(cluster);
    }

    return {
        init,
        updateEarthquakes,
        updateConflictZones,
        updateHotspots,
        updateBases,
        updateNuclear,
        updateWaterways,
        updateCables,
        updateDisasters,
        updateConflictEvents,
        loadLayerData,
    };
})();
