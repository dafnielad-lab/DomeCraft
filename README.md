# DomeCraft 🏟️

**An interactive CAD-style tool for designing polygonal and circular domes from a hand-drawn profile — with live 3D preview, cross-sections, supports, flattened fabrication stencils, and DXF export.**

Draw the dome's profile curve with your mouse (or import it from a DXF file), and the app instantly computes the full dome geometry: the 3D surface, a true-scale plan view, polygonal cross-sections for supports, and flattened segment stencils ready for cutting. Everything updates **live** while you drag sliders and control points — no page reloads, no view resets.

Geometry and mathematics designed by **Elad (Layogev)**.

---

## ✨ Features

- **🎯 Drawing board** — place control points with the mouse, drag them to reshape the profile, right-click to delete. A smooth monotone spline (PCHIP) passes exactly through every point.
- **📥 DXF import** — use any curve from a DXF file as the profile (polylines, splines, arcs, and chained line segments are all recognized; the longest curve is auto-selected).
- **🏟️ Live 3D dome** — polygonal (N facets, inscribed/circumscribed) or circular, rendered with an exact parametric facet mesh, skeleton ribs, and orthographic projection (true angles, CAD-style).
- **🗺️ Plan view** — a flat top view at guaranteed 1:1 scale for inspecting the polygon symmetry.
- **📈 Cross-sections** — section curves of all facets along a cutting plane at distance `a` and angle `t`, with the exact section envelope, cut precisely at the dome edge.
- **✨ Flattened stencils** — each dome segment unrolled by arc length into a flat cutting template, with mirror and full rotation pattern.
- **📤 DXF export** — sections (with envelopes) and flattened stencils, ready for CNC/laser cutting.
- **🖥️ 2×2 grid view** — all four graphs on one screen, updating together live.
- **⚡ Truly live updates** — custom slider and chart components stream values *while dragging*; the camera, zoom, and pan you set are preserved across every update.

## 🧮 The math (in short)

- **Profile**: `z = f(r)` defined by control points, interpolated with a shape-preserving PCHIP spline (no overshoot between points). Outside the drawn range the dome simply ends.
- **Polygonal dome**: each facet is the profile extruded along the facet edge. A point belongs to its **nearest facet** (maximal projection), so the surface is `z = f(max_i dist_i)` — correct even for profiles that curl back up at the rim.
- **Footprint cut**: a point is part of the dome only if it lies on the inner side of *all* facet edges; sections and supports stop exactly at the dome edge.
- **Flattening**: arc length computed by chord sums `s = Σ √(Δr² + Δz²)` (robust for any drawn curve, including vertical tangents); stencil half-width is `r·sin(π/N)` (inscribed) or `r·tan(π/N)` (circumscribed).

## 🚀 Installation & Run

Requires Python 3.10+.

```bash
pip install -r requirements.txt
streamlit run DomeCraft.py
```

On Windows you can simply double-click **`Launch_DomeCraft.bat`** — it starts the app and installs missing packages automatically on first run.

The app opens in your browser at `http://localhost:8501`.

> Note: on first run the app writes a local copy of `plotly.min.js` into `live_chart/` (so it works offline). This file is intentionally not committed.

## 📖 How to use

1. **Draw the profile** on the board at the top: click to add a point, drag to move, right-click to delete. `r` is the distance from the dome's center (apex at `r = 0`), `z` is the height. The outermost point sets the dome radius `A`.
   - Wheel = zoom, Shift+drag = pan, **Fit** = frame the points, **Reset** = default profile.
   - Or upload a **DXF** in the sidebar — the curve becomes the profile (x = radius, y = height).
2. **Set the geometry** in the sidebar: number of sides `N`, base shape (Polygon/Circular), and polygon scale mode (Inscribed/Circumscribed).
3. **Explore sections** with the live sliders:
   - `Distance (a)` — the cutting plane's distance from the center (exact value can be typed in the box).
   - `Angle (t)` — the cutting plane's direction (1 = 360°).
   - Supports are drawn at spacing `Spacing`, `Sections/Side` on each side of `a`.
4. **Check the graphs**: 3D dome (rotate/zoom freely — the view survives every update), plan view, 2D sections, and the flattened stencils.
5. **Export DXF**: `Export Sections` writes every section curve plus the blue envelope per cut; `Export Stencils` writes the flattened templates (with mirror + rotation if shown).
6. **2×2 Grid View** (checkbox at the top of the sidebar) shows all four graphs on one screen for live design work.

## 📁 Project structure

| Path | What it is |
|---|---|
| `DomeCraft.py` | The whole app: geometry engine, UI, DXF import/export |
| `points_canvas/index.html` | Custom drawing-board component (mouse editing, JS PCHIP preview) |
| `live_chart/index.html` | Persistent chart component — in-place Plotly updates, view preservation |
| `live_slider/index.html` | Slider that streams values while dragging |
| `Launch_DomeCraft.bat` | One-click Windows launcher |

---

# DomeCraft — קונסול כיפה מנקודות בקרה 🏟️

**כלי אינטראקטיבי בסגנון CAD לתכנון כיפות מצולעות ועגולות מתוך פרופיל מצויר ביד — עם תצוגת תלת-ממד חיה, חתכים, תומכות, פריסות שטוחות לחיתוך, וייצוא DXF.**

מציירים את עקום הפרופיל של הכיפה עם העכבר (או מייבאים מקובץ DXF), והאפליקציה מחשבת מיד את כל הגיאומטריה: משטח תלת-ממדי, מבט-על בקנה מידה אמיתי, חתכים מצולעים לתומכות, ופריסות מקטעים שטוחות מוכנות לחיתוך. הכל מתעדכן **חי** תוך כדי גרירת סליידרים ונקודות.

תכנון הגיאומטריה והמתמטיקה: **אלעד**.

## איך משתמשים

1. **מציירים את הפרופיל** בלוח שבראש המסך: לחיצה מוסיפה נקודה, גרירה מזיזה, לחיצה ימנית מוחקת. ‏`r` = מרחק ממרכז הכיפה (הקודקוד ב-0), ‏`z` = גובה. הנקודה החיצונית קובעת את רדיוס הכיפה.
   - גלגלת = זום, ‏Shift+גרירה = הזזה, ‏Fit = מסגור הנקודות, ‏Reset = פרופיל ברירת מחדל.
   - אפשר גם להעלות **DXF** בסרגל הצד — העקום הופך לפרופיל (x = רדיוס, y = גובה).
2. **קובעים גיאומטריה** בסרגל: מספר צלעות `N`, צורת בסיס (מצולע/עיגול), ומצב חסום/חוסם.
3. **חוקרים חתכים** עם הסליידרים החיים: `a` = מרחק מישור החיתוך מהמרכז (אפשר להקליד ערך מדויק בשדה), ‏`t` = כיוון המישור. התומכות מצוירות במרווחים לפי הגדרות הייצוא.
4. **בודקים את הגרפים**: כיפה תלת-ממדית (סיבוב וזום נשמרים בין עדכונים), מבט-על, חתכים, ופריסות.
5. **מייצאים DXF**: חתכים + מעטפות, או פריסות (כולל שיקוף וסיבוב מלא).
6. **תצוגת 2×2** (תיבה בראש הסרגל) — כל ארבעת הגרפים על מסך אחד לעבודת תכנון חיה.

## התקנה

דרוש Python 3.10 ומעלה.

```bash
pip install -r requirements.txt
streamlit run DomeCraft.py
```

בווינדוס אפשר פשוט ללחוץ פעמיים על `Launch_DomeCraft.bat` — ההפעלה הראשונה תתקין אוטומטית חבילות חסרות.
