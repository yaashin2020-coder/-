# CLAUDE.md — まとめてルート

## What this project is

**まとめてルート** ("Batch Route") is a Japanese-language PWA that helps users find nearby chain stores and calculate an optimized multi-stop driving route. It runs entirely in the browser with no build step.

## File structure

```
index.html     — The entire app: HTML markup, CSS, and JavaScript in one file
manifest.json  — PWA manifest (name, icons, display mode)
```

There is no package.json, no bundler, no test suite, and no server-side code. Everything is vanilla HTML/CSS/JS.

## Tech stack

- **Vanilla JavaScript (ES2020+)** — async/await, Set, spread, optional chaining
- **Google Maps JavaScript API** — Places library (`Place.searchByText`), `google.maps.Map`, `Marker`, `Polyline`, `LatLngBounds`
- **Google Routes API v2** — `https://routes.googleapis.com/directions/v2:computeRoutes` called directly via `fetch`
- **PWA** — `manifest.json`, iOS `<meta>` tags, `env(safe-area-inset-*)` for notch-safe layout

## API keys

Both `API_KEY` (line 311) and `MAPS_API_KEY` (line 640) in `index.html` hold the same Google Cloud API key. They must be identical and must have the following APIs enabled on the Google Cloud project:

- Maps JavaScript API
- Places API (New)
- Routes API

## App architecture — 4-step wizard

| Step | DOM id | Purpose |
|------|--------|---------|
| 1 | `step-location` | Acquire GPS position via `navigator.geolocation` |
| 2 | `step-chains` | User selects chain store brands (preset + custom) |
| 3 | `step-stores` | Nearby stores are fetched; user picks up to 5 |
| 4 | `step-map` | Route calculated, polyline drawn, info shown |

Navigation is driven by `showStep(n)` which hides/shows the four step divs and updates the progress dots.

## Global state

All mutable state lives in the `app` object (defined at line 378):

```js
app.location           // { lat, lng } — current GPS position
app.selectedChainIds   // Set<string> — chosen chain IDs
app.customChains       // Array<{id, name, icon, kw}> — user-added chains
app.radius             // number (metres) — search radius, default 5000
app.foundStores        // Array<store> — results from Places API, sorted by distance
app.selectedPlaceIds   // Set<string> — place IDs the user has ticked
app.orderedStores      // Array<store> — route-optimized order from Routes API
app.routeResult        // raw Routes API JSON response
app.map                // google.maps.Map instance
app.directionsRenderer // unused; kept for legacy compatibility
```

## Chain store data

`CHAIN_DATA` (line 316) is a plain object keyed by category slug. Each entry is an array of chain descriptors:

```js
{ id: string, name: string, icon: string, kw: string }
```

`kw` is the Japanese keyword sent to `Place.searchByText`. `GRID_MAP` maps category slugs to DOM element IDs.

## Key functions

| Function | Location | Role |
|----------|----------|------|
| `initApp()` | ~line 394 | Google Maps `callback=` entry point |
| `getLocation()` | ~line 469 | Geolocation, transitions to step 2 |
| `doSearch()` | ~line 506 | Fires parallel `searchChain` calls, renders results progressively |
| `searchChain(chain)` | ~line 570 | Single `Place.searchByText` call |
| `calcRoute()` | ~line 657 | Calls Routes API, draws polyline/markers |
| `renderRouteInfo()` | ~line 760 | Populates the route summary card |
| `openGoogleMaps()` | ~line 812 | Builds a `google.com/maps/dir/` deep-link |
| `showStep(n)` | ~line 831 | Single source of truth for screen transitions |
| `restart()` | ~line 841 | Resets all app state back to step 2 |
| `haverDist(a, b)` | ~line 860 | Haversine distance in metres |
| `esc(s)` | ~line 878 | XSS-safe HTML escaping via `textContent` |

## Development workflow

There is no build step. Edit `index.html` and open it in a browser, or serve it with any static file server:

```bash
python3 -m http.server 8080
# then open http://localhost:8080
```

GPS access requires HTTPS in production (most browsers also allow `localhost`).

## Conventions

- **Single file** — keep HTML, CSS, and JS together in `index.html`. Do not split into separate files unless the user explicitly requests it.
- **No dependencies** — do not introduce npm, bundlers, or external CSS/JS libraries.
- **Japanese UI** — all user-visible strings must remain in Japanese.
- **iOS/PWA safe areas** — use `env(safe-area-inset-*)` for paddings near the notch/home bar; do not use fixed pixel values there.
- **XSS safety** — always pass user-generated or API-returned strings through `esc()` before inserting into `innerHTML`.
- **Store cap** — `foundStores` is sliced to 40 items and the user may select at most 5 stores (enforced in `toggleStore`).
- **Routes API field mask** — the `X-Goog-FieldMask` header controls billing; only request fields that are actually consumed.
- **No comments on obvious code** — add a comment only when the reason is non-obvious (e.g., the `parseInt(leg.duration)` call strips the trailing `"s"` from duration strings returned by the Routes API).

## PWA icons

`manifest.json` references `icon-192.png` and `icon-512.png`. These are not present in the repository; they must be added before the PWA install prompt works.
