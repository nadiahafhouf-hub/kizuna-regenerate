# Farmer Page Overrides

> **PROJECT:** Verdix
> **Generated:** 2026-11-22 05:27:52
> **Page Type:** Dashboard / Data View

> ⚠️ **IMPORTANT:** Rules in this file **override** the Master file (`design-system/MASTER.md`).
> Only deviations from the Master are documented here. For all other rules, refer to the Master.

---

## Page-Specific Rules

### Layout Overrides

- **Max Width:** 1400px or full-width
- **Grid:** 12-column grid for data flexibility
- **Sections:** Hero > Bento Grid (Key Features) > Detail Cards > Tech Specs > CTA

### Spacing Overrides

- **Content Density:** High — optimize for information display

### Typography Overrides

- No overrides — use Master typography

### Color Overrides

- **Strategy:** Card backgrounds: #F5F5F7 or Glass. Icons: Vibrant brand colors. Text: Dark.

### Component Overrides

- Avoid: Icon buttons without labels
- Avoid: Use a clickable div or reveal the only action on hover
- Avoid: Block paste or require manual OTP transcription with no alternative

---

## Page-Specific Components

- No unique components for this page

---

## Recommendations

- Effects: grid-template with varied spans, rounded-xl (16px), subtle shadows, hover scale (1.02), smooth transitions
- Accessibility: Add aria-label for icon-only buttons
- Accessibility: Prefer a button and expose pressed or selected state that matches the visible label
- Security / Accessibility: Allow password managers and paste; offer passkeys OAuth or another non-cognitive method
- CTA Placement: Floating Action Button or Bottom of Grid
