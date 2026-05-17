# SahayakMap Layout Handoff

Source of truth: `/root/Sahayak/deploy/templates/index.html`

## 1. Layout Hierarchy

```text
body
- div#map
- header#topbar
  - div.logo
    - div.logo-mark
    - div.logo-name
      - small
  - div.spacer
  - div.pills
    - span#pill-normal.pill.ok
      - span.dot
      - span#pill-normal-txt
    - span#pill-warn.pill.warn
      - span.dot
      - span#pill-warn-txt
    - span#pill-danger.pill.bad
      - span.dot
      - span#pill-danger-txt
    - span#pill-stale.pill.stale
      - span.dot
      - span#pill-stale-txt
  - span#clock.mono
- div#banner
  - div.b-icon
  - div
    - b#banner-title
    - span#banner-sub.b-sub
  - button#banner-act.b-act
- nav#rail
  - button.rail-btn[data-panel="stations"]
    - svg
    - span.tip
  - button.rail-btn[data-panel="alerts"]
    - svg
    - span#rail-alerts-badge.badge.warn
    - span.tip
  - button.rail-btn[data-panel="weather"]
    - svg
    - span.tip
  - button.rail-btn[data-panel="social"]
    - svg
    - span.tip
  - button.rail-btn[data-panel="teams"]
    - svg
    - span.tip
  - button.rail-btn[data-panel="kpi"]
    - svg
    - span.tip
  - div.rail-spacer
- aside#side-panel
  - div.panel-hd
    - h3#panel-title
    - span#panel-count.count
    - button.panel-close
  - div#panel-content.panel-body
- section#station-drawer
  - div.drawer-info
    - div.drawer-hd
      - div
        - h2#drawer-name
        - div#drawer-river.sub
      - button.panel-close
    - div#drawer-status.drawer-status
    - div
      - button#forecast-tab.drawer-tab.active
      - button#sos-tab.drawer-tab
      - button#obs-tab.drawer-tab
    - div#drawer-grid.kv-grid
    - div.drawer-meta
      - span#drawer-updated
      - span#drawer-stale
  - div#forecast-div.drawer-chart-wrap
    - div.chart-hd
      - span.title
    - div#drawer-chart
  - div#sos-div
    - div
    - div#sos-content
  - div#obs-div
    - div#obs-content
- nav#bottom-nav
  - button.nav-btn[data-panel="stations"]
    - svg
    - span
  - button.nav-btn[data-panel="alerts"]
    - svg
    - span#nav-alerts-badge.badge
    - span
  - button.nav-btn[data-panel="weather"]
    - svg
    - span
  - button.nav-btn[data-panel="social"]
    - svg
    - span
  - button.nav-btn[data-panel="teams"]
    - svg
    - span
  - button.nav-btn[data-panel="kpi"]
    - svg
    - span
- button#chat-fab.chat-fab
- section#chat-panel.chat-panel
  - div.chat-hd
    - div.title
    - button.chat-close
  - div#chat-messages.chat-messages
  - form#chat-form.chat-form
    - input#chat-input.chat-input
    - button#chat-send.chat-send
```

## 2. Component List

- Sidebar icons + panel names:
  - Stations
  - Alerts
  - IMD Weather
  - Social + News
  - Team Comms
  - KPI
- Station list item structure:
  - `.row`
  - `.pill-circle` status glyph
  - `.body`
    - `.name`
    - `.sub`
  - `.right`
    - `.num`
    - `.delta`
- Station drawer:
  - Header: name, river/district, close
  - Status pill
  - Tabs: `Forecast`, `SOS`, `Obs`
  - KPI grid: current WSE, AI Fcst +8h, warning, danger
  - Forecast panel: Plotly chart
  - SOS panel: route/boat intelligence
  - Obs panel: bulletin observations card
- Map container:
  - `#map` Leaflet surface
  - custom station markers
  - aircraft markers
  - boat markers
  - SOS marker/lines
- Topbar pills:
  - Normal
  - Warning
  - Danger
  - Stale
  - clock chip
- Chat bubble + panel:
  - floating FAB `#chat-fab`
  - slide-up panel `#chat-panel`
  - header, messages, input, send
- IMD Weather panel:
  - list rows rendered in `#panel-content`
  - station name + weather emoji
  - rain/wind line
  - issued/valid lines
  - optional Sachet alert list below
- Social + News panel:
  - tab row: Twitter / WhatsApp / News
  - social message cards
  - news alert cards
- KPI panel:
  - `kpi-sec`, `kpi-card`, `kpi-row`
  - sections: Data Health, Pipeline Health, Operational
- Team Comms panel:
  - WSE state header strip
  - `.team-row` list with avatar, name, role, status

## 3. CSS Class Inventory

```text
active, aircraft-marker, alert-card, av, away, b-act, b-icon, b-sub, bad, badge, boat-marker, body, bot, chart-hd, chat-close, chat-fab, chat-form, chat-hd, chat-input, chat-messages, chat-msg, chat-panel, chat-send, citizen, count, danger, delta, deployed, dot, down, drawer-chart-wrap, drawer-hd, drawer-info, drawer-meta, drawer-status, drawer-tab, empty, fc, k, kpi-card, kpi-row, kpi-sec, kpi-sec-hd, kv, kv-grid, leaflet-control-attribution, leaflet-control-zoom, leaflet-popup-content, leaflet-popup-content-wrapper, leaflet-popup-tip, leaflet-right, leaflet-tooltip, leaflet-top, logo, logo-mark, logo-name, marker-wrap, meta, mono, name, nav-btn, neutral, no_data, normal, num, ok, on-shift, open, panel-body, panel-close, panel-hd, panel-open, pill, pill-circle, pills, rail-btn, rail-spacer, right, ring, role, row, sel, show, social, sos-marker, spacer, sr-only, src-tag, stale, stat, station-marker, sub, tab-btn, tab-row, team-row, text, tip, title, top, up, user, v, warn, warning
```

## 4. Full Current Stylesheet

```css
/* ══════════════════════════════════════════════════════════════
   SAHAYAKMAP · Professional, fully responsive (desktop → mobile)
   ══════════════════════════════════════════════════════════════ */

:root{
  /* Neutrals */
  --bg:#f5f4f0; --panel-bg:#ffffff; --panel-2:#faf9f6; --panel-3:#f1efe9;
  --ink-1:#181a18; --ink-2:#525551; --ink-3:#8a8c87; --ink-4:#b9bab4;
  --line:#ebe9e3; --line-2:#dcd9d1;
  /* Brand */
  --accent:#1f4e8a; --accent-2:#3a82c9; --accent-soft:#e6eef7; --accent-3:#0f3a6e;
  /* Semantic */
  --ok:#1f6e44;   --ok-2:#e2efe6;
  --warn:#a8650a; --warn-2:#fbeed2;
  --bad:#9e2a26;  --bad-2:#f6d8d4;
  --amber:#e08c0c;
  /* Geometry */
  --radius:12px; --radius-sm:8px; --radius-xs:5px; --gap:14px;
  --rail-w:60px; --topbar-h:56px; --panel-w:360px; --drawer-h:320px;
  --bottom-nav-h:60px;
  /* Elevation */
  --shadow-sm:0 1px 2px rgba(20,18,12,.05);
  --shadow-md:0 8px 24px -10px rgba(20,18,12,.16),0 2px 8px rgba(20,18,12,.05);
  --shadow-lg:0 24px 60px -20px rgba(20,18,12,.24),0 6px 16px rgba(20,18,12,.07);
  /* Z-index scale */
  --z-rail:1200; --z-topbar:950; --z-banner:1050; --z-panel:1100; --z-drawer:1180; --z-tip:2000;
  /* Type */
  --font-sans:"Manrope",ui-sans-serif,system-ui,-apple-system,sans-serif;
  --font-mono:"JetBrains Mono",ui-monospace,monospace;
  /* Motion */
  --t:220ms cubic-bezier(.4,.1,.2,1);
  --t-slow:340ms cubic-bezier(.4,.1,.2,1);
}

*,*::before,*::after{margin:0;padding:0;box-sizing:border-box}
html,body{height:100%;overflow:hidden;-webkit-text-size-adjust:100%}
body{
  font-family:var(--font-sans);font-size:14px;line-height:1.5;
  color:var(--ink-1);background:var(--bg);
  -webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale;
  text-rendering:optimizeLegibility;font-feature-settings:"ss01","cv11";
}
button{font:inherit;color:inherit;cursor:pointer;background:none;border:0}
button:focus-visible,a:focus-visible,input:focus-visible{
  outline:2px solid var(--accent);outline-offset:2px;border-radius:6px;
}
.mono{font-family:var(--font-mono);font-feature-settings:"tnum","zero"}
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);border:0}

/* ─── MAP ─────────────────────────────────────────────── */
#map{position:absolute;inset:0;z-index:0;background:var(--panel-3)}
.leaflet-top.leaflet-right{margin-top:var(--topbar-h)}
.leaflet-control-attribution{
  background:rgba(255,255,255,.9)!important;font-size:10px!important;
  color:var(--ink-3)!important;border-radius:6px!important;padding:2px 8px!important;
  border:1px solid var(--line)!important;
}
.leaflet-control-zoom{
  border:1px solid var(--line)!important;border-radius:10px!important;
  overflow:hidden;box-shadow:var(--shadow-md)!important;margin:16px!important;
}
.leaflet-control-zoom a{
  background:var(--panel-bg)!important;color:var(--ink-1)!important;
  border-bottom:1px solid var(--line)!important;
  width:34px!important;height:34px!important;line-height:34px!important;font-size:18px!important;
  font-weight:300!important;
}
.leaflet-control-zoom a:last-child{border-bottom:0!important}
.leaflet-control-zoom a:hover{background:var(--panel-2)!important;color:var(--accent)!important}

/* ─── TOP BAR ─────────────────────────────────────────── */
#topbar{
  position:fixed;top:0;left:0;right:0;z-index:var(--z-topbar);
  height:var(--topbar-h);background:var(--panel-bg);
  border-bottom:1px solid var(--line);
  display:flex;align-items:center;padding:0 16px;gap:14px;
  padding-top:env(safe-area-inset-top,0);
}
#topbar::after{
  content:"";position:absolute;left:0;right:0;bottom:-6px;height:6px;
  background:linear-gradient(180deg,rgba(20,18,12,.04),transparent);pointer-events:none;
}
#topbar .logo{
  display:flex;align-items:center;gap:11px;
  padding-right:16px;border-right:1px solid var(--line);height:100%;
  min-width:calc(var(--rail-w) + 152px - 16px);
}
#topbar .logo-mark{
  width:30px;height:30px;border-radius:8px;
  background:linear-gradient(140deg,var(--accent-2) 0%,var(--accent) 60%,var(--accent-3) 100%);
  display:grid;place-items:center;color:#fff;font-weight:800;font-size:14px;
  box-shadow:0 1px 0 rgba(255,255,255,.35) inset,0 4px 10px rgba(31,78,138,.32);
  letter-spacing:-.02em;
}
#topbar .logo-name{font-weight:700;font-size:15px;letter-spacing:-.005em;line-height:1.1}
#topbar .logo-name small{
  display:block;font-size:10.5px;color:var(--ink-3);font-weight:500;
  text-transform:uppercase;letter-spacing:.08em;margin-top:1px;
}
#topbar .spacer{flex:1}
#topbar .pills{display:flex;gap:6px;align-items:center;flex-wrap:nowrap}
.pill{
  padding:5px 12px;border-radius:999px;font-size:12px;font-weight:600;
  display:inline-flex;align-items:center;gap:7px;white-space:nowrap;
  background:var(--panel-2);border:1px solid var(--line);color:var(--ink-2);
  transition:background var(--t),border-color var(--t);
}
.pill .dot{width:7px;height:7px;border-radius:50%;background:currentColor;flex-shrink:0}
.pill.ok{color:var(--ok);background:var(--ok-2);border-color:transparent}
.pill.ok .dot{box-shadow:0 0 0 3px rgba(31,110,68,.16)}
.pill.warn{color:var(--warn);background:var(--warn-2);border-color:transparent}
.pill.warn .dot{box-shadow:0 0 0 3px rgba(168,101,10,.18);animation:soft-pulse 2.2s ease-in-out infinite}
.pill.bad{color:var(--bad);background:var(--bad-2);border-color:transparent}
.pill.bad .dot{box-shadow:0 0 0 3px rgba(158,42,38,.18);animation:soft-pulse 1.4s ease-in-out infinite}
.pill.stale{color:#9ca3af;background:#f3f4f6;border-color:transparent}
.pill.stale .dot{box-shadow:0 0 0 3px rgba(156,163,175,.18)}
@keyframes soft-pulse{
  0%,100%{box-shadow:0 0 0 3px rgba(158,42,38,.18)}
  50%    {box-shadow:0 0 0 7px rgba(158,42,38,.06)}
}
#clock{
  font-family:var(--font-mono);font-size:12px;color:var(--ink-3);
  display:inline-flex;align-items:center;gap:6px;
  padding:5px 11px;border:1px solid var(--line);border-radius:999px;background:var(--panel-2);
}
#clock::before{content:"";width:6px;height:6px;border-radius:50%;background:var(--ok)}

/* ─── CRITICAL BANNER ─────────────────────────────────── */
#banner{
  position:fixed;top:calc(var(--topbar-h) + 14px);left:50%;
  transform:translate(-50%,-16px);opacity:0;pointer-events:none;
  z-index:var(--z-banner);
  display:flex;align-items:center;gap:12px;
  background:var(--panel-bg);border:1px solid var(--warn);
  border-radius:999px;padding:8px 8px 8px 16px;
  font-size:13px;box-shadow:var(--shadow-lg);
  max-width:min(560px,calc(100% - var(--rail-w) - 40px));
  transition:opacity var(--t-slow),transform var(--t-slow);
}
#banner.show{opacity:1;transform:translate(-50%,0);pointer-events:auto}
#banner.danger{border-color:var(--bad)}
#banner .b-icon{
  width:26px;height:26px;border-radius:50%;display:grid;place-items:center;
  background:var(--warn-2);color:var(--warn);flex-shrink:0;
}
#banner.danger .b-icon{background:var(--bad-2);color:var(--bad)}
#banner b{font-weight:600;letter-spacing:-.005em}
#banner .b-sub{color:var(--ink-3);font-size:12px;margin-left:6px}
#banner button.b-act{
  height:30px;padding:0 14px;border-radius:999px;
  background:var(--ink-1);color:var(--panel-bg);font-size:12px;font-weight:600;
  transition:background var(--t),transform var(--t);
}
#banner button.b-act:hover{background:var(--accent);transform:translateY(-1px)}
#banner button.b-act:active{transform:translateY(0)}

/* ─── ICON RAIL ───────────────────────────────────────── */
#rail{
  position:fixed;top:var(--topbar-h);left:0;bottom:0;z-index:var(--z-rail);
  width:var(--rail-w);background:var(--panel-bg);border-right:1px solid var(--line);
  display:flex;flex-direction:column;align-items:center;padding:14px 0;gap:4px;
  padding-bottom:max(14px,env(safe-area-inset-bottom));
}
.rail-btn{
  position:relative;width:42px;height:42px;border-radius:10px;
  color:var(--ink-3);display:grid;place-items:center;
  transition:color var(--t),background var(--t),transform var(--t);
}
.rail-btn:hover{color:var(--ink-1);background:var(--panel-2)}
.rail-btn:active{transform:scale(.94)}
.rail-btn.active{color:var(--accent);background:var(--accent-soft)}
.rail-btn.active::before{
  content:"";position:absolute;left:-12px;top:50%;transform:translateY(-50%);
  width:3px;height:22px;border-radius:0 3px 3px 0;background:var(--accent);
}
.rail-btn svg{width:21px;height:21px;stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round;fill:none;stroke:currentColor}
.rail-btn .badge{
  position:absolute;top:4px;right:4px;min-width:16px;height:16px;padding:0 4px;
  border-radius:8px;background:var(--bad);color:#fff;font-family:var(--font-mono);
  font-size:9.5px;font-weight:700;display:grid;place-items:center;
  border:2px solid var(--panel-bg);
}
.rail-btn .badge.warn{background:var(--warn)}
.rail-btn .tip{
  position:absolute;left:calc(100% + 12px);top:50%;transform:translateY(-50%);
  background:var(--ink-1);color:var(--panel-bg);
  padding:6px 10px;border-radius:6px;font-size:12px;font-weight:500;white-space:nowrap;
  opacity:0;pointer-events:none;transition:opacity var(--t),transform var(--t);
  z-index:var(--z-tip);
}
.rail-btn .tip::before{
  content:"";position:absolute;left:-4px;top:50%;transform:translateY(-50%) rotate(45deg);
  width:8px;height:8px;background:var(--ink-1);
}
.rail-btn:hover .tip{opacity:1;transform:translateY(-50%) translateX(2px)}
.rail-spacer{flex:1}

/* ─── SIDE PANEL ──────────────────────────────────────── */
#side-panel{
  position:fixed;top:var(--topbar-h);left:var(--rail-w);bottom:0;z-index:var(--z-panel);
  width:var(--panel-w);background:var(--panel-bg);border-right:1px solid var(--line);
  transform:translateX(-105%);transition:transform var(--t-slow);
  display:flex;flex-direction:column;box-shadow:var(--shadow-md);
}
#side-panel.open{transform:translateX(0)}
.panel-hd{
  display:flex;align-items:center;gap:10px;
  padding:16px 18px;border-bottom:1px solid var(--line);flex-shrink:0;
  background:linear-gradient(180deg,var(--panel-bg),var(--panel-2));
}
.panel-hd h3{
  font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;
  color:var(--ink-1);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
}
.panel-hd .count{
  font-family:var(--font-mono);font-size:11px;color:var(--ink-3);
  background:var(--panel-bg);border:1px solid var(--line);
  padding:3px 9px;border-radius:999px;font-weight:600;
}
.panel-close{
  width:30px;height:30px;border-radius:7px;color:var(--ink-3);
  display:grid;place-items:center;transition:background var(--t),color var(--t);
}
.panel-close:hover{background:var(--panel-3);color:var(--ink-1)}
.panel-body{flex:1;overflow-y:auto;padding:4px 0;-webkit-overflow-scrolling:touch}
.panel-body::-webkit-scrollbar{width:8px}
.panel-body::-webkit-scrollbar-thumb{background:var(--line-2);border-radius:4px;border:2px solid transparent;background-clip:content-box}
.panel-body::-webkit-scrollbar-thumb:hover{background:var(--ink-3);background-clip:content-box;border:2px solid transparent}
.empty{color:var(--ink-3);font-size:13px;padding:40px 20px;text-align:center;line-height:1.6}

/* ─── ROWS ────────────────────────────────────────────── */
.row{
  display:flex;align-items:center;gap:12px;padding:12px 18px;
  cursor:pointer;border-bottom:1px solid var(--line);
  transition:background var(--t),box-shadow var(--t);
}
.row:hover{background:var(--panel-2)}
.row.sel{background:var(--accent-soft);box-shadow:inset 3px 0 0 var(--accent)}
.row.sel .body .name{color:var(--accent-3)}
.row .pill-circle{
  width:32px;height:32px;border-radius:50%;display:grid;place-items:center;
  color:#fff;font-weight:700;font-size:12.5px;flex-shrink:0;
  border:2px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,.14);letter-spacing:-.02em;
}
.row .pill-circle.normal{background:var(--ok)}
.row .pill-circle.warning{background:var(--warn)}
.row .pill-circle.danger{background:var(--bad)}
.row .pill-circle.no_data{background:var(--ink-3)}
.row .body{flex:1;min-width:0}
.row .body .name{font-weight:600;font-size:14px;color:var(--ink-1);
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;letter-spacing:-.005em}
.row .body .sub{font-size:11.5px;color:var(--ink-3);margin-top:2px;
  display:flex;gap:6px;flex-wrap:wrap;align-items:center}
.row .body .sub b{color:var(--ink-2);font-weight:600}
.row .right{text-align:right;flex-shrink:0}
.row .right .num{font-family:var(--font-mono);font-size:14px;font-weight:600;color:var(--ink-1)}
.row .right .num small{color:var(--ink-3);font-weight:400;font-size:10.5px;margin-left:2px}
.row .right .delta{font-family:var(--font-mono);font-size:11px;color:var(--ink-3);margin-top:2px}
.row .right .delta.up{color:var(--warn);font-weight:600}
.row .right .delta.down{color:var(--ok);font-weight:600}

/* ─── ALERTS / SOCIAL ─────────────────────────────────── */
.alert-card{
  padding:14px 18px;border-bottom:1px solid var(--line);
  border-left:3px solid transparent;transition:background var(--t);
}
.alert-card:hover{background:var(--panel-2)}
.alert-card.danger{border-left-color:var(--bad);
  background:linear-gradient(90deg,var(--bad-2),transparent 70%)}
.alert-card.warning{border-left-color:var(--warn);
  background:linear-gradient(90deg,var(--warn-2),transparent 70%)}
.alert-card .title{font-weight:600;font-size:13.5px;line-height:1.35;margin-bottom:5px;letter-spacing:-.005em}
.alert-card .body{font-size:12.5px;color:var(--ink-2);line-height:1.55}
.alert-card .meta{font-size:11px;color:var(--ink-3);margin-top:8px;
  display:flex;gap:12px;flex-wrap:wrap;align-items:center}

.social{padding:13px 18px;border-bottom:1px solid var(--line);transition:background var(--t)}
.social:hover{background:var(--panel-2)}
.social .top{display:flex;gap:8px;align-items:center;font-size:11.5px;color:var(--ink-3)}
.social .src-tag{
  font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;
  padding:2px 7px;border-radius:4px;background:var(--accent-soft);color:var(--accent);
}
.social .src-tag.citizen{background:var(--ok-2);color:var(--ok)}
.social .text{margin-top:6px;font-size:13px;color:var(--ink-1);line-height:1.5}

/* ─── TEAM ───────────────────────────────────────────── */
.team-row{display:flex;align-items:center;gap:12px;padding:13px 18px;
  border-bottom:1px solid var(--line);transition:background var(--t)}
.team-row:hover{background:var(--panel-2)}
.team-row .av{width:34px;height:34px;border-radius:50%;display:grid;place-items:center;
  color:#fff;font-weight:600;font-size:11.5px;flex-shrink:0;letter-spacing:-.02em;
  box-shadow:0 1px 3px rgba(0,0,0,.14)}
.team-row .body{flex:1;min-width:0}
.team-row .body .name{font-weight:600;font-size:13.5px;letter-spacing:-.005em}
.team-row .body .role{font-size:12px;color:var(--ink-3);margin-top:1px}
.team-row .stat{font-size:11px;font-weight:600;padding:3px 10px;border-radius:999px;text-transform:capitalize}
.team-row .stat.on-shift{background:var(--ok-2);color:var(--ok)}
.team-row .stat.deployed{background:var(--warn-2);color:var(--warn)}
.team-row .stat.away{background:var(--panel-3);color:var(--ink-3);border:1px solid var(--line)}

/* ─── KPI ────────────────────────────────────────────── */
.kpi-sec{padding:12px 0 2px}
.kpi-sec-hd{
  padding:0 18px 8px;font-size:11px;font-weight:700;letter-spacing:.06em;
  text-transform:uppercase;color:#6b7280;
}
.kpi-card{
  margin:0 12px 12px;border:1px solid var(--line);border-radius:8px;
  background:var(--panel-bg);overflow:hidden;
}
.kpi-row{
  display:flex;justify-content:space-between;gap:12px;align-items:flex-start;
  padding:12px 14px;border-top:1px solid var(--line);
}
.kpi-row:first-child{border-top:0}
.kpi-row .k{font-size:12px;color:var(--ink-3);line-height:1.4}
.kpi-row .v{font-size:15px;font-weight:700;line-height:1.25;color:var(--ink-1);text-align:right}
.kpi-row .v.ok{color:var(--ok)}
.kpi-row .v.warn{color:var(--warn)}
.kpi-row .v.bad{color:var(--bad)}
.kpi-row .v.neutral{color:#9ca3af}

/* ─── TABS ────────────────────────────────────────────── */
.tab-row{display:flex;gap:2px;padding:6px 14px 0;border-bottom:1px solid var(--line);background:var(--panel-2)}
.tab-btn{
  padding:10px 14px;font-size:12.5px;font-weight:500;color:var(--ink-3);
  border-bottom:2px solid transparent;margin-bottom:-1px;transition:color var(--t);
}
.tab-btn.active{color:var(--accent);border-bottom-color:var(--accent);font-weight:600}
.tab-btn:hover:not(.active){color:var(--ink-2)}

/* ─── DRAWER ──────────────────────────────────────────── */
#station-drawer{
  position:fixed;bottom:16px;right:16px;z-index:var(--z-drawer);
  left:calc(var(--rail-w) + 16px);height:var(--drawer-h);
  background:var(--panel-bg);border:1px solid var(--line);
  border-radius:var(--radius);box-shadow:var(--shadow-lg);
  display:flex;overflow:hidden;
  transform:translateY(calc(100% + 32px));opacity:0;pointer-events:none;
  transition:transform var(--t-slow),opacity var(--t-slow),left var(--t-slow);
}
#station-drawer.open{transform:translateY(0);opacity:1;pointer-events:auto}
body.panel-open #station-drawer{left:calc(var(--rail-w) + var(--panel-w) + 16px)}

.drawer-info{
  width:312px;padding:18px 20px;border-right:1px solid var(--line);
  display:flex;flex-direction:column;gap:12px;flex-shrink:0;overflow-y:auto;
  background:linear-gradient(180deg,var(--panel-bg),var(--panel-2));
}
.drawer-hd{display:flex;justify-content:space-between;align-items:flex-start;gap:8px}
.drawer-hd h2{font-size:18px;font-weight:700;line-height:1.2;letter-spacing:-.015em;
  overflow:hidden;text-overflow:ellipsis}
.drawer-hd .sub{font-size:12.5px;color:var(--ink-3);margin-top:3px}
.drawer-status{
  display:inline-flex;align-items:center;gap:6px;
  font-size:11px;font-weight:700;padding:4px 10px;border-radius:999px;
  background:var(--ok-2);color:var(--ok);align-self:flex-start;
  text-transform:uppercase;letter-spacing:.05em;
}
.drawer-status::before{content:"";width:6px;height:6px;border-radius:50%;background:currentColor}
.drawer-status.warning{background:var(--warn-2);color:var(--warn)}
.drawer-status.danger {background:var(--bad-2); color:var(--bad)}
.drawer-status.no_data{background:var(--panel-3);color:var(--ink-3);border:1px solid var(--line)}

.kv-grid{display:grid;grid-template-columns:1fr 1fr;gap:7px;margin-top:2px}
.kv{
  padding:9px 11px;background:var(--panel-bg);border:1px solid var(--line);border-radius:8px;
  transition:border-color var(--t);
}
.kv:hover{border-color:var(--line-2)}
.kv .k{font-size:10px;color:var(--ink-3);text-transform:uppercase;letter-spacing:.06em;font-weight:600}
.kv .v{font-family:var(--font-mono);font-size:14.5px;font-weight:600;color:var(--ink-1);margin-top:2px;display:block;letter-spacing:-.01em}
.kv .v small{font-size:10px;color:var(--ink-3);font-weight:400;margin-left:2px}
.kv.warn .v{color:var(--warn)}
.kv.bad  .v{color:var(--bad)}
.kv.fc   .v{color:var(--accent)}
.kv.fc   {border-color:var(--accent-soft);background:linear-gradient(180deg,var(--accent-soft),var(--panel-bg))}

.drawer-meta{font-size:11.5px;color:var(--ink-3);display:flex;justify-content:space-between;
  margin-top:auto;padding-top:8px;border-top:1px solid var(--line)}
.drawer-meta .stale{color:var(--warn);font-weight:600}

.drawer-chart-wrap{flex:1;display:flex;flex-direction:column;padding:14px 16px 10px;min-width:0}
.drawer-chart-wrap .chart-hd{
  display:flex;justify-content:space-between;align-items:center;
  font-size:11.5px;color:var(--ink-3);margin-bottom:6px;
}
.drawer-chart-wrap .chart-hd .title{
  font-size:11.5px;font-weight:700;color:var(--ink-1);
  text-transform:uppercase;letter-spacing:.06em;
}
.drawer-tab{padding:4px 8px;font-size:11px;font-weight:500;border:none;border-radius:6px;background:#f3f4f6;color:#374151;cursor:pointer;transition:all var(--t)}
.drawer-tab.active{background:#ef4444;color:#fff}
#drawer-chart{flex:1;width:100%;min-height:0}

/* ─── MARKERS ─────────────────────────────────────────── */
.marker-wrap{background:transparent;border:0}
.station-marker{
  width:32px;height:32px;border-radius:50%;display:grid;place-items:center;
  font-family:var(--font-sans);font-weight:700;font-size:12.5px;color:#fff;
  border:2.5px solid #fff;box-shadow:0 2px 8px rgba(0,0,0,.28);
  position:relative;cursor:pointer;transition:transform var(--t);
  letter-spacing:-.02em;
}
.station-marker:hover{transform:scale(1.14)}
.station-marker.normal{background:var(--ok)}
.station-marker.warning{background:var(--warn)}
.station-marker.danger{background:var(--bad)}
.station-marker.no_data{background:var(--ink-3)}
.station-marker .ring{
  position:absolute;inset:-3px;border-radius:50%;
  border:2.5px solid currentColor;animation:ring 1.8s ease-out infinite;pointer-events:none;
}
@keyframes ring{0%{transform:scale(.85);opacity:.75}100%{transform:scale(2);opacity:0}}
.aircraft-marker{background:transparent;border:0;font-size:14px;text-align:center}
.boat-marker{background:transparent;border:0;font-size:20px;line-height:24px;text-align:center}
.sos-marker{background:transparent;border:0;font-size:22px;line-height:24px;text-align:center}
.chat-fab{
  position:fixed;right:18px;bottom:18px;z-index:1290;
  width:48px;height:48px;border-radius:50%;
  background:#1f4e8a;color:#fff;display:grid;place-items:center;
  box-shadow:var(--shadow-lg);font-size:22px;transition:transform var(--t),background var(--t);
}
.chat-fab:hover{background:var(--accent-3);transform:translateY(-1px)}
.chat-panel{
  position:fixed;right:18px;bottom:76px;z-index:1290;
  width:300px;height:400px;border-radius:12px;
  background:var(--panel-bg);border:1px solid var(--line);
  box-shadow:var(--shadow-lg);display:flex;flex-direction:column;
  overflow:hidden;opacity:0;pointer-events:none;transform:translateY(10px);
  transition:opacity var(--t),transform var(--t);
}
.chat-panel.open{opacity:1;pointer-events:auto;transform:translateY(0)}
.chat-hd{
  display:flex;align-items:center;justify-content:space-between;gap:10px;
  padding:12px 14px;border-bottom:1px solid var(--line);
  background:linear-gradient(180deg,var(--panel-bg),var(--panel-2));
}
.chat-hd .title{font-size:13px;font-weight:700;letter-spacing:.01em;color:var(--ink-1)}
.chat-close{
  width:28px;height:28px;border-radius:7px;color:var(--ink-3);
  display:grid;place-items:center;transition:background var(--t),color var(--t);
}
.chat-close:hover{background:var(--panel-3);color:var(--ink-1)}
.chat-messages{
  flex:1;overflow-y:auto;padding:12px;display:flex;flex-direction:column;gap:10px;
  background:var(--panel-2);-webkit-overflow-scrolling:touch;
}
.chat-msg{max-width:88%;padding:9px 11px;border-radius:10px;font-size:12.5px;line-height:1.5;white-space:pre-wrap}
.chat-msg.user{align-self:flex-end;background:var(--accent);color:#fff;border-bottom-right-radius:4px}
.chat-msg.bot{align-self:flex-start;background:var(--panel-bg);color:var(--ink-1);border:1px solid var(--line);border-bottom-left-radius:4px}
.chat-msg.meta{align-self:center;background:transparent;color:var(--ink-3);font-size:11px;padding:0}
.chat-form{
  display:flex;gap:8px;padding:10px 12px;border-top:1px solid var(--line);background:var(--panel-bg);
}
.chat-input{
  flex:1;min-width:0;height:38px;padding:0 12px;border-radius:9px;border:1px solid var(--line);
  background:var(--panel-2);color:var(--ink-1);font:inherit;
}
.chat-send{
  height:38px;padding:0 14px;border-radius:9px;background:var(--accent);color:#fff;
  font-size:12px;font-weight:700;transition:background var(--t);
}
.chat-send:hover{background:var(--accent-3)}
.chat-send:disabled{background:#9ca3af;cursor:default}

.leaflet-popup-content-wrapper{
  border-radius:10px!important;box-shadow:var(--shadow-lg)!important;
  border:1px solid var(--line);
}
.leaflet-popup-content{font-family:var(--font-sans);font-size:13px;color:var(--ink-1);margin:12px 14px;line-height:1.55}
.leaflet-popup-tip{box-shadow:none!important}
.leaflet-tooltip{background:var(--panel-bg);color:var(--ink-1);border:1px solid var(--line);border-radius:6px;padding:4px 8px;font-size:12px;font-weight:500;box-shadow:var(--shadow-sm)}

/* ─── MOBILE BOTTOM NAV ───────────────────────────────── */
#bottom-nav{
  display:none;position:fixed;bottom:0;left:0;right:0;z-index:var(--z-rail);
  height:var(--bottom-nav-h);background:var(--panel-bg);border-top:1px solid var(--line);
  padding:6px 4px;padding-bottom:max(6px,env(safe-area-inset-bottom));
  justify-content:space-around;align-items:center;box-shadow:0 -4px 12px rgba(20,18,12,.04);
}
#bottom-nav .nav-btn{
  flex:1;max-width:80px;display:flex;flex-direction:column;align-items:center;gap:3px;
  padding:6px 4px;color:var(--ink-3);position:relative;border-radius:8px;
}
#bottom-nav .nav-btn.active{color:var(--accent)}
#bottom-nav .nav-btn svg{width:22px;height:22px;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round;fill:none;stroke:currentColor}
#bottom-nav .nav-btn span{font-size:10.5px;font-weight:600;letter-spacing:-.005em}
#bottom-nav .nav-btn .badge{
  position:absolute;top:4px;right:14px;min-width:14px;height:14px;padding:0 3px;
  border-radius:7px;background:var(--bad);color:#fff;font-family:var(--font-mono);
  font-size:9px;font-weight:700;display:grid;place-items:center;border:1.5px solid var(--panel-bg);
}

/* ─── RESPONSIVE BREAKPOINTS ──────────────────────────── */
/* Tablet — collapse panel chrome a bit */
@media(max-width:1100px){
  :root{--panel-w:320px;--drawer-h:300px}
}
/* Small tablet — drawer becomes bottom sheet, panel sits over map */
@media(max-width:900px){
  :root{--panel-w:300px;--drawer-h:280px}
  #side-panel{box-shadow:var(--shadow-lg)}
  body.panel-open #station-drawer{left:calc(var(--rail-w) + 16px)}
}
/* Mobile */
@media(max-width:720px){
  :root{
    --rail-w:0;--panel-w:100vw;--topbar-h:52px;--drawer-h:54vh;
  }
  #rail{display:none}
  #bottom-nav{display:flex}
  #topbar{padding:0 12px;gap:10px}
  #topbar .logo{
    min-width:auto;border-right:0;padding-right:0;gap:9px;
  }
  #topbar .logo-mark{width:28px;height:28px;font-size:13px}
  #topbar .logo-name{font-size:14px}
  #topbar .logo-name small{display:none}
  #topbar #clock{display:none}
  #topbar .pills .pill{padding:4px 10px;font-size:11.5px}
  #topbar .pills .pill .dot{width:6px;height:6px}
  #bottom-nav{z-index:1300}
  #side-panel{
    left:0;width:100vw;top:var(--topbar-h);
    bottom:var(--bottom-nav-h);box-shadow:none;border-right:0;
  }
  #station-drawer{
    left:8px!important;right:8px;bottom:calc(var(--bottom-nav-h) + 8px);
    height:var(--drawer-h);flex-direction:column;
  }
  body.panel-open #station-drawer{left:8px!important}
  .drawer-info{
    width:100%;border-right:0;border-bottom:1px solid var(--line);
    padding:14px 16px;max-height:50%;
  }
  .drawer-info .drawer-meta{margin-top:8px}
  .drawer-chart-wrap{padding:10px 12px 8px;min-height:120px}
  #banner{
    top:auto;bottom:calc(var(--bottom-nav-h) + var(--drawer-h) + 14px);
    left:8px;right:8px;transform:translateY(20px);max-width:none;
    transition:opacity var(--t-slow),transform var(--t-slow);
  }
  #banner.show{transform:translateY(0)}
  #banner .b-sub{display:none}
  .row{padding:11px 14px}
  .alert-card{padding:12px 14px}
  .social,.team-row{padding:11px 14px}
  .chat-fab{right:12px;bottom:calc(var(--bottom-nav-h) + 12px)}
  .chat-panel{
    left:12px;right:12px;bottom:calc(var(--bottom-nav-h) + 68px);
    width:auto;height:min(400px,calc(100vh - var(--topbar-h) - var(--bottom-nav-h) - 96px));
  }
}
/* Very small phones */
@media(max-width:380px){
  #topbar .pills .pill.ok{display:none}
  #topbar .logo-name{font-size:13px}
}
/* Landscape mobile — keep drawer compact */
@media(max-height:520px) and (orientation:landscape){
  :root{--drawer-h:200px}
  .kv-grid{grid-template-columns:repeat(4,1fr)}
}

/* Reduce motion */
@media(prefers-reduced-motion:reduce){
  *,*::before,*::after{animation-duration:.01ms!important;transition-duration:.01ms!important}
}
```

## 5. Color Variables In Use

| Variable | Value |
|---|---|
| `--bg` | `#f5f4f0` |
| `--panel-bg` | `#ffffff` |
| `--panel-2` | `#faf9f6` |
| `--panel-3` | `#f1efe9` |
| `--ink-1` | `#181a18` |
| `--ink-2` | `#525551` |
| `--ink-3` | `#8a8c87` |
| `--ink-4` | `#b9bab4` |
| `--line` | `#ebe9e3` |
| `--line-2` | `#dcd9d1` |
| `--accent` | `#1f4e8a` |
| `--accent-2` | `#3a82c9` |
| `--accent-soft` | `#e6eef7` |
| `--accent-3` | `#0f3a6e` |
| `--ok` | `#1f6e44` |
| `--ok-2` | `#e2efe6` |
| `--warn` | `#a8650a` |
| `--warn-2` | `#fbeed2` |
| `--bad` | `#9e2a26` |
| `--bad-2` | `#f6d8d4` |
| `--amber` | `#e08c0c` |

## 6. Font Stack

- Primary font variable: `--font-sans: "Manrope", ui-sans-serif, system-ui, -apple-system, sans-serif`
- Monospace font variable: `--font-mono: "JetBrains Mono", ui-monospace, monospace`
- External font import:
  - `Manrope` weights `400,500,600,700,800`
  - `JetBrains Mono` weights `400,500,600`

## 7. Full Body HTML Structure (layout section only)

```html
<div id="map" role="application" aria-label="Odisha river map"></div>

<!-- TOP BAR -->
<header id="topbar" role="banner">
  <div class="logo">
    <div class="logo-mark" aria-hidden="true">S</div>
    <div class="logo-name">SahayakMap<small>Odisha · Flood Ops</small></div>
  </div>
  <div class="spacer"></div>
  <div class="pills" role="status" aria-live="polite">
    <span class="pill ok" id="pill-normal"><span class="dot"></span><span id="pill-normal-txt">— Normal</span></span>
    <span class="pill warn" id="pill-warn" style="display:none"><span class="dot"></span><span id="pill-warn-txt">0 Warning</span></span>
    <span class="pill bad"  id="pill-danger" style="display:none"><span class="dot"></span><span id="pill-danger-txt">0 Danger</span></span>
    <span class="pill stale" id="pill-stale" style="display:none"><span class="dot"></span><span id="pill-stale-txt">0 Stale</span></span>
  </div>
  <span class="mono" id="clock" aria-label="Current time">--:--</span>
</header>

<!-- CRITICAL BANNER -->
<div id="banner" role="alert" aria-live="assertive">
  <div class="b-icon" aria-hidden="true">
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m12 3 10 18H2z"/><path d="M12 10v5"/><circle cx="12" cy="18" r=".8" fill="currentColor"/></svg>
  </div>
  <div style="flex:1;min-width:0">
    <b id="banner-title">—</b>
    <span class="b-sub" id="banner-sub"></span>
  </div>
  <button class="b-act" id="banner-act">Review</button>
</div>

<!-- RAIL (desktop) -->
<nav id="rail" aria-label="Primary">
  <button class="rail-btn active" data-panel="stations" aria-label="Stations">
    <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 -2 24 26" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <line x1="12" y1="20" x2="12" y2="12"/>
      <path d="M8 20L12 12l4 8"/>
      <path d="M6 8a6 6 0 0 1 12 0"/>
      <path d="M3 5a10 10 0 0 1 18 0"/>
    </svg>
    <span class="tip">Stations</span>
  </button>
  <button class="rail-btn" data-panel="alerts" aria-label="Alerts">
    <svg viewBox="0 0 24 24"><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/></svg>
    <span class="badge warn" id="rail-alerts-badge" style="display:none">0</span>
    <span class="tip">Alerts</span>
  </button>
  <button class="rail-btn" data-panel="weather" aria-label="IMD Weather">
    <svg viewBox="0 0 24 24"><path d="M17.5 19a4.5 4.5 0 1 0-1.4-8.79 6 6 0 0 0-11.6 2.29A4 4 0 0 0 6 19z"/></svg>
    <span class="tip">IMD Weather</span>
  </button>
  <button class="rail-btn" data-panel="social" aria-label="Social and News">
    <svg viewBox="0 0 24 24"><path d="M4 11a9 9 0 0 1 9 9"/><path d="M4 4a16 16 0 0 1 16 16"/><circle cx="5" cy="19" r="1.4" fill="currentColor" stroke="none"/></svg>
    <span class="tip">Social + News</span>
  </button>
  <button class="rail-btn" data-panel="teams" aria-label="Team Comms">
    <svg viewBox="0 0 24 24"><circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><circle cx="17" cy="9" r="2.6"/><path d="M21.5 19a4.5 4.5 0 0 0-7-3.7"/></svg>
    <span class="tip">Team Comms</span>
  </button>
  <button class="rail-btn" data-panel="kpi" aria-label="KPI">
    <svg viewBox="0 0 24 24"><path d="M5 19V9"/><path d="M12 19V5"/><path d="M19 19v-7"/><path d="M3 19h18"/></svg>
    <span class="tip">KPI</span>
  </button>
  <div class="rail-spacer"></div>
</nav>

<!-- SIDE PANEL -->
<aside id="side-panel" aria-label="Detail panel">
  <div class="panel-hd">
    <h3 id="panel-title">Stations</h3>
    <span class="count" id="panel-count">—</span>
    <button class="panel-close" onclick="closePanel()" aria-label="Close panel">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6 18 18M18 6 6 18"/></svg>
    </button>
  </div>
  <div class="panel-body" id="panel-content"></div>
</aside>

<!-- STATION DRAWER -->
<section id="station-drawer" aria-label="Station detail">
  <div class="drawer-info">
    <div class="drawer-hd">
      <div style="min-width:0">
        <h2 id="drawer-name">—</h2>
        <div class="sub" id="drawer-river"></div>
      </div>
      <button class="panel-close" onclick="closeDrawer()" aria-label="Close detail">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6 18 18M18 6 6 18"/></svg>
      </button>
    </div>
    <div class="drawer-status" id="drawer-status">Normal</div>
    <div style="display:flex;gap:4px;margin:8px 0">
      <button class="drawer-tab active" id="forecast-tab" onclick="switchDrawerTab('forecast')">📈 Forecast</button>
      <button class="drawer-tab" id="sos-tab" onclick="switchDrawerTab('sos')">🆘 SOS</button>
      <button class="drawer-tab" id="obs-tab" onclick="switchDrawerTab('obs')">🌡️ Obs</button>
    </div>
    <div class="kv-grid" id="drawer-grid"></div>
    <div class="drawer-meta">
      <span id="drawer-updated">Updated —</span>
      <span id="drawer-stale"></span>
    </div>
  </div>
   <div class="drawer-chart-wrap" id="forecast-div">
     <div class="chart-hd">
       <span class="title">WSE · 30-day · AI Forecast</span>
     </div>
     <div id="drawer-chart"></div>
   </div>
   <div id="sos-div" hidden style="padding:16px 18px;min-height:320px;overflow:auto;font-size:12px;line-height:1.6;background:var(--panel-2)">
     <div style="font-weight:600;margin-bottom:8px;color:var(--accent)">🆘 SOS Intelligence</div>
     <div id="sos-content"><div style="color:var(--ink-3)">Select SOS tab to load</div></div>
   </div>
   <div id="obs-div" hidden style="padding:16px 18px;min-height:320px;overflow:auto;font-size:12px;line-height:1.6;background:var(--panel-2)">
     <div id="obs-content"><div style="color:var(--ink-3)">Select Obs tab to load</div></div>
   </div>
 </section>

<!-- BOTTOM NAV (mobile) -->
<nav id="bottom-nav" aria-label="Primary (mobile)">
  <button class="nav-btn active" data-panel="stations">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M4 6h16M4 12h16M4 18h16"/></svg>
    <span>Stations</span>
  </button>
  <button class="nav-btn" data-panel="alerts">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/></svg>
    <span class="badge" id="nav-alerts-badge" style="display:none">0</span>
    <span>Alerts</span>
  </button>
  <button class="nav-btn" data-panel="weather">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M17.5 19a4.5 4.5 0 1 0-1.4-8.79 6 6 0 0 0-11.6 2.29A4 4 0 0 0 6 19z"/></svg>
    <span>Weather</span>
  </button>
  <button class="nav-btn" data-panel="social">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M4 11a9 9 0 0 1 9 9"/><path d="M4 4a16 16 0 0 1 16 16"/><circle cx="5" cy="19" r="1.4" fill="currentColor" stroke="none"/></svg>
    <span>Feed</span>
  </button>
  <button class="nav-btn" data-panel="teams">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><circle cx="17" cy="9" r="2.6"/><path d="M21.5 19a4.5 4.5 0 0 0-7-3.7"/></svg>
    <span>Teams</span>
  </button>
  <button class="nav-btn" data-panel="kpi">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M5 19V9"/><path d="M12 19V5"/><path d="M19 19v-7"/><path d="M3 19h18"/></svg>
    <span>KPI</span>
  </button>
</nav>

<button class="chat-fab" id="chat-fab" aria-label="Open intelligence chat" title="SahayakMap Intel" onclick="toggleChat()">🤖</button>
<section class="chat-panel" id="chat-panel" aria-label="SahayakMap Intelligence Chat">
  <div class="chat-hd">
    <div class="title">SahayakMap Intel</div>
    <button class="chat-close" aria-label="Close chat" onclick="closeChat()">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6 18 18M18 6 6 18"/></svg>
    </button>
  </div>
  <div class="chat-messages" id="chat-messages"></div>
  <form class="chat-form" id="chat-form">
    <input class="chat-input" id="chat-input" type="text" placeholder="Ask about gauges, weather, tweets..." autocomplete="off">
    <button class="chat-send" id="chat-send" type="submit">Send</button>
  </form>
</section>
```
