# Deprecated — 2026-08-09

This repo is no longer the source of anything.

- The renderer lives at `tailscale-network/global/scripts/printable.py`
  (deployed as `/usr/local/bin/printable`). The copy that used to sit here had
  drifted and was never the one any host ran.
- The A4 design standard and its toolchain moved to
  `universe-skills/global/skills/creative/a4-onepager/`.
- The fleet print pipeline is documented in
  `universe-skills/global/skills/devops/printing/` and `universe/docs/PRINTING.md`.
- Printing now goes through `printctl` on **star**, not the macbook watcher.
