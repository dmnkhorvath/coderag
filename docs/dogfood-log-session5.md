# Dogfood Session 5: Cal.com (Turborepo TS+React+Tailwind)

**Date:** 2026-03-22
**Repository:** calcom/cal.com
**Type:** Turborepo monorepo — TypeScript + React + Next.js + Tailwind CSS
**Commit:** 18b5fc3

## Repository Stats
- **Files:** 7,530 (7,467 TS/TSX, 43 JS/JSX, 19 CSS/SCSS, 1 PHP)
- **Size:** 553 MB
- **Structure:** Turborepo monorepo with `apps/web`, `apps/api`, 20+ packages

## Parse Results
| Metric | Value |
|--------|-------|
| Files Found | 7,530 |
| Files Parsed | 7,530 (100%) |
| Total Nodes | 50,926 |
| Total Edges | 220,752 |
| Communities | 1,268 (Leiden) |
| Avg Confidence | 0.72 |
| Parse Time | 335s (~5.5 min) |
| DB Size | 316 MB |

## Node Distribution
| Kind | Count |
|------|-------|
| class | 9,188 |
| property | 8,278 |
| function | 7,887 |
| file | 7,529 |
| method | 5,956 |
| constant | 5,183 |
| type_alias | 3,714 |
| css_class | 3,558 |
| interface | 1,360 |
| css_variable | 1,084 |

## Edge Distribution
| Kind | Count |
|------|-------|
| calls | 42,197 |
| contains | 38,995 |
| imports | 34,483 |
| uses_css_class | 16,057 |
| exports | 13,581 |
| has_type | 8,595 |
| imports_type | 6,873 |
| renders | 5,980 |
| passes_prop | 4,755 |
| returns_type | 4,427 |
| instantiates | 3,373 |

## Frameworks Detected (after fix)
- **Next.js:** 452 routes, 1,002 components
- **React:** 2,514 components, 403 hooks
- **Tailwind CSS:** detected

## Cross-Language Matching
- Endpoints found: 451
- API calls found: 246
- Matches: 11
- Edges: 10

## Bugs Found and Fixed

### Bug 1 (HIGH): React/NextJS/Express not detected in monorepos
**Symptom:** Only Tailwind detected despite Cal.com being a React/Next.js app.
**Root cause:** ReactDetector, NextJSDetector, and ExpressDetector only checked root `package.json`. In monorepos like Cal.com, dependencies live in `apps/web/package.json`.
**Fix:** Added monorepo subdirectory scanning (packages/*, apps/*, src/*, frontend/*, client/*) to all three detectors, matching the pattern already used by VueDetector (fixed in session 4).
**Impact:** All JS framework detectors now work in monorepos.

### Bug 2 (MEDIUM): NextJSDetector missing from TypeScript plugin
**Symptom:** Next.js not detected even if root package.json had `next` dependency.
**Root cause:** NextJSDetector was only registered in the JavaScript plugin, not the TypeScript plugin. Cal.com has 7,467 TS files but only 43 JS files.
**Fix:** Added NextJSDetector to TypeScript plugin's `get_framework_detectors()` alongside React, Angular, Vue.

### Bug 3 (MEDIUM): Search returns external nodes before internal nodes
**Symptom:** `coderag query 'App' --kind class` returned 10 external placeholder nodes with `<external>` file paths and 0-0 lines.
**Root cause:** FTS5 search ordered by `rank` alone, which doesn't distinguish internal from external nodes.
**Fix:** Added `CASE WHEN n.file_path = '<external>' THEN 1 ELSE 0 END` to ORDER BY in both FTS5 and LIKE-based search queries.

### Bug 4 (LOW): CSS utility classes dominate top PageRank display
**Symptom:** `coderag info` showed .flex, .items-center, .text-sm as top PageRank nodes.
**Root cause:** Tailwind utility classes have thousands of `uses_css_class` edges, inflating their PageRank disproportionately.
**Fix:** Excluded CSS node kinds (css_class, css_variable, css_id, css_keyframes, css_layer, css_media_query, css_font_face) and external nodes from the top PageRank display in `get_summary()`.

## Verification After Fix
- ✅ Frameworks: nextjs, react, tailwind all detected
- ✅ Top PageRank: useLocale (0.001877), hasPermission (0.000143) — real code symbols
- ✅ Search: BookingPage returns 5 internal results with real file paths and line numbers
- ✅ Cross-language: 10 API route-to-fetch connections found
- ✅ All 3,614 tests passing

## Cumulative Dogfood Totals (5 sessions)
| Session | Repo | Nodes | Edges | Bugs |
|---------|------|-------|-------|------|
| 1 | koel (PHP+Vue) | 13,384 | 36,709 | 2 |
| 2 | paperless-ngx (Django+Angular) | 20,580 | 50,517 | 0 |
| 3 | saleor (Django+GraphQL) | 111,076 | 260,654 | 3 |
| 4 | NocoDB (TS+Vue monorepo) | 24,367 | 74,284 | 4 |
| 5 | Cal.com (TS+React+Tailwind) | 50,926 | 220,752 | 4 |
| **Total** | | **220,333** | **642,916** | **13** |
