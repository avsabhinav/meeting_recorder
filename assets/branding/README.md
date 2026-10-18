# Brand assets

- `appIcon-iOS.png` — 1024×1024 full-color app icon (exported from the Icon Composer
  document). Used as the product/brand image in `README.md`.
- `app.icns` — the macOS app-bundle icon, generated from `appIcon-iOS.png`
  (`sips` resize → `.iconset` → `iconutil -c icns`). Copied into the built
  `Oatmeal.app` as `Contents/Resources/app.icns` (wired via `CFBundleIconFile`).
- `appIcon.icon/` — the macOS 14+ Icon Composer source document for the app icon
  (editing source; not consumed by the app build directly).
- `icon-white.png` — white glyph, transparent background. The menu-bar status icon's
  **IDLE** image, used as an **AppKit template image** (grayscale; template rendering
  supplies the built-in active/click highlight).
- `appIcon-recording.png` — full-color glyph (transparent background). The menu-bar status
  icon's **RECORDING** image, rendered **non-template** so its colors show — so the icon
  visibly changes when a capture is live (alongside the OS's own orange recording indicator).