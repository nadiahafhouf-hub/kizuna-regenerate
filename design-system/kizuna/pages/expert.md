# Expert Page Overrides

> **PROJECT:** Kizuna
> **Generated:** 2026-11-22 05:27:52
> **Page Type:** Dashboard / Data View

> ⚠️ **IMPORTANT:** Rules in this file **override** the Master file (`design-system/MASTER.md`).
> Only deviations from the Master are documented here. For all other rules, refer to the Master.

---

## Page-Specific Rules

### Layout Overrides

- **Max Width:** 1400px or full-width
- **Grid:** 12-column grid for data flexibility

### Spacing Overrides

- **Content Density:** High — optimize for information display

### Typography Overrides

- No overrides — use Master typography

### Color Overrides

- No overrides — use Master colors

### Component Overrides

- Avoid: Single row actions only
- Avoid: Auto-play high-resolution loops without pause or captions
- Avoid: Use rainbow or jet ramps, which add false boundaries and uneven lightness, or saturated data colors on a busy saturated basemap

---

## Page-Specific Components

- No unique components for this page

---

## Recommendations

- Effects: Hover tooltips, chart zoom on click, row highlighting on hover, smooth filter animations, data loading spinners
- Data Entry: Allow multi-select and bulk edit
- Sustainability: Prefer click-to-play; provide pause and captions; stop off-screen and honor reduced motion
- Maps: Use single-hue sequential or perceptually uniform ramps (Viridis, ColorBrewer sequential) and diverging ramps only around a meaningful midpoint; darker means more on a light basemap and brighter means more on a dark basemap; mute basemap saturation so the data layer stays strongest
