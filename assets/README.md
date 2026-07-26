# Brand assets

convoy's visual identity. The SVGs are self-contained — every shape is a drawn
path, no font or network dependency — and they are the source of truth: edit
them as code; don't retype the wordmark in a font or re-export from a design
tool.

| File | What | Where it's used |
|---|---|---|
| `convoy-mark-{light,dark}.svg` | The mark alone: accent tile with the double-chevron figure cut out as true transparency | Favicon / avatar; anything down to 16 px |
| `convoy-wordmark-{light,dark}.svg` | The drawn wordmark alone | Inline naming |
| `convoy-lockup-{light,dark}.svg` | Mark + wordmark | Headers |
| `convoy-hero-{light,dark}.svg` | 1280×240 banner: framed, centered lockup | Top of [README.md](../README.md) |
| `convoy-social-card.svg` / `.png` | 1280×640 dark card: lockup over a figure watermark | GitHub Settings → Social preview (upload the PNG) |

## Embedding

GitHub renders READMEs in both light and dark; embed the theme pair with
`<picture>`:

```html
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/convoy-hero-dark.svg">
  <img alt="convoy" src="assets/convoy-hero-light.svg" width="100%">
</picture>
```

The same pattern applies to the mark and the lockup.

## Tokens and rules

- Accent (signal amber): tile `#A45E05` on light, `#C17930` on dark; accent
  text `#7F4400` on light, `#D89C67` on dark. Neutrals: ink `#171B1F`, paper
  `#FBFBFA`, muted `#5C666E`, badge-label `#2A3238`.
- Badges: shields.io `flat-square`, always `labelColor=2A3238`; version/meta
  badges use `7F4400`; CI/status badges keep shields' semantic defaults; at
  most five in the row.
- The tile is never outlined, recolored per context, or rotated; minimum mark
  size 16 px.
- The assets carry no text beyond the wordmark.
