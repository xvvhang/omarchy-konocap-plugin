# Changelog

## 1.1.0 — 2026-11-05

- Rename Focus Titlebars to **Konocap**, part of the Konochi plugin series.
- Use `konochi.konocap` for the Omarchy plugin ID and status IPC target.
- Rename the GitHub repository to `xvvhang/omarchy-konocap-plugin` and update
  installation URLs and existing-checkout migration instructions.
- Align manifest, native module version, build metadata, logs, and documentation.
- Confirm compatibility with Omarchy **4.5.0-3 stable**, Hyprland **0.56.2-4**,
  and `omarchy-hyprland-titlebars` **0.2.2-2** using the isolated regression suite.
- Read settings from legacy `xvvhang.focus-titlebars` / `alec.focus-titlebars`
  entries when no canonical entry exists. Native library, lock, and cache names
  remain unchanged to keep upgrades serialized and safe.
- No titlebar behavior changes: 180ms reveal / 120ms retract, focus-only drawing,
  and automatic stock restoration remain the defaults.

## 1.0.0 — 2026-11-04

- Initial Focus Titlebars release as a self-contained Omarchy service plugin.
- Automatic native builds, focus-only sliding titlebars, theme integration,
  pidfd-based crash recovery, and isolated lifecycle/rendering tests.
