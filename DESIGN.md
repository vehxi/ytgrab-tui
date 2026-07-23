# YTGRAB — Design Direction

## 1. Visual Theme and Atmosphere

YTGRAB is a raw local-media console: near-black green graphite, restrained
signal colors, square rails, and a custom three-point terminal mark. It should
feel like a small operator instrument rather than a dashboard or landing page.

The mark is a deliberately low-resolution adaptation of a three-ray geometric
silhouette. Its central diamond and one-cell pixel shadow create depth without
changing the surrounding interface or requiring an image asset.

## 2. Color Palette and Roles

- `canvas`: `#0C100D` — green-tinted near-black working field.
- `surface`: `#141A16` — input and progress surfaces.
- `active`: `#202820` — focused rows and text selection.
- `text`: `#E5EADF` — soft primary text, never pure white.
- `muted`: `#707D72` — metadata and inactive shortcuts.
- `line`: `#344038` — functional rails and quiet boundaries.
- `amber`: `#EFB84B` — logo, progress, focus, and intentional emphasis.
- `signal`: `#8FAF76` — ready/success state and product descriptor.
- `danger`: `#E57066` — errors and destructive feedback only.
- `ink`: `#0C100D` — text placed on bright controls.

## 3. Typography Rules

The user's terminal monospace is the only typeface. Uppercase is reserved for
section labels, transfer stages, and system state; normal copy stays lowercase.
Dynamic percentages and timers remain visually stable because monospace digits
are naturally tabular. The graphical mark uses only common Unicode geometry and
block characters.

## 4. Component Styling

- Inputs and lists use open `tall` rails rather than rounded boxes.
- Buttons use a solid light surface; focus changes to amber without changing the
  three-row footprint.
- The selected format uses a dark-green lift and amber text.
- Progress occupies exactly the format list's space and never shifts the action.
- Toasts are square, dark, and lightly tinted by their semantic state.
- Disabled actions stay visible so the layout does not reflow.

## 5. Layout Principles

The working area is centered and capped at 104 columns. The masthead groups the
mark, purpose, and local status. Source and result are mutually exclusive views:
the user always sees one decision at a time. Empty space is structural and is
not filled with generic cards.

## 6. Depth and Elevation

The surrounding UI has no decorative shadows. Depth comes from canvas, surface,
and active-surface luminance steps. The logo alone has a fixed one-cell
down-right pixel shadow, keeping the requested visual effect scoped to the mark.

## 7. Do's and Don'ts

- Keep the three-point mark visible in every state.
- Use amber for focus and motion, green for readiness and completion.
- Keep source and format numbered as `01` and `02`.
- Keep keyboard and mouse behavior equivalent.
- Preserve control dimensions during loading, progress, cancellation, and retry.
- Do not add gradients, rounded cards, blurred shadows, or extra accent families.
- Do not turn the masthead into a marketing hero.
- Do not include machine-specific paths or user data in screenshots.

## 8. Responsive Behavior

At more than 96 columns, formats and metadata sit side by side. At 96 columns or
less they stack and the system badge disappears. At 64 columns or less the
supporting line is hidden and the inspect action moves below the URL. Interactive
controls stay at least three terminal rows high.

## 9. Agent Prompt Guide

Use Textual CSS only for layout and Rich markup only for the logo. Tokens: canvas
`#0C100D`, surface `#141A16`, active `#202820`, text `#E5EADF`, muted `#707D72`,
line `#344038`, amber `#EFB84B`, signal `#8FAF76`, danger `#E57066`, ink
`#0C100D`.

- Build controls with square `tall` rails and fixed three-row hit areas.
- Use the amber three-point Unicode mark with a `#263329` one-cell shadow as the
  single visual anchor.
- Animate the mark only by cycling muted, signal, and amber colors.
- Keep the interface cardless and centered at a maximum of 104 columns.
- Verify every state at 140×42 and 60×42 terminal cells.
