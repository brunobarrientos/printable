---
name: printable
description: "Build print-ready A4 PDFs from Markdown / JSON / text on any fleet device, then scp to macbook's PrintQueue drop folder for the local watcher to print. Sender is responsible for layout; watcher is a strict PDF/image pass-through."
version: 1.0.0
author: Hermes Agent + Bruno
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [printing, fleet, printable, pdf, cups, printqueue]
    homepage: ~/AI/printable/
---

# printable — fleet print pipeline

Build a real A4 PDF on **any** fleet device (hetzner / desk / netcup / macbook),
then scp it to macbook's PrintQueue drop folder. The local macOS CUPS queue
(`HP_DeskJet_2700_series`) prints it. No shared CUPS, no firewall changes,
no IPP plumbing — just a folder and a 30-line watcher.

The script lives at `~/AI/printable/printable.py` on every host. It is
stdlib + reportlab; reportlab is installed via apt (`python3-reportlab` on
Debian/Ubuntu) or pip on macOS (`/usr/bin/pip3 install --user reportlab`).

## The boundary rule

**Senders prepare A4 PDFs. The watcher does not convert.**

The macbook watcher accepts only `.pdf` (and image files like `.png`,
`.jpg`) directly. Anything else — `.txt`, `.md`, `.json`, `.csv`, etc. —
is moved to `~/PrintQueue/failed/` with a `.reason.txt` sidecar pointing
back to this skill. There is **no** text→PDF auto-conversion on macbook;
the watcher would have to guess the page layout, font, line length, and
that's not its job.

Senders (`hetzner`, `desk`, `netcup`, anywhere else) build a real A4 PDF
using `printable.py`, then `scp` it to macbook. macbook just prints.

## End-to-end workflow (verified 2026-07-25)

```bash
# On hetzner (or any sender):
cd ~/AI/printable
./printable.py --title "JP Future Authoring (Mini)" ~/notes/jp_mini.md -o /tmp/jp.pdf
# -> /tmp/jp.pdf is a real A4 PDF, 3 pages, 5,961 bytes

# Pre-exchange macbook's SSH host key once (one-time per sender):
ssh-keyscan -H macbook.spaniel-orfe.ts.net >> ~/.ssh/known_hosts

# Push to macbook's drop folder:
scp /tmp/jp.pdf brunobarrientos@macbook.spaniel-orfe.ts.net:PrintQueue/inbox/

# That's it. The watcher (running on macbook) prints it within ~2 seconds.
# Check the queue:
ssh macbook 'tail -3 ~/PrintQueue/watcher.log'
ssh macbook 'lpstat'
```

## printable.py — usage

```bash
printable [--title "..."] [--format auto|md|txt|json|pdf] INPUT -o OUTPUT.pdf
```

- **Input**: a file path, or stdin if you omit `INPUT`.
- **Output**: a file path (use `-` only when piping to a tool that reads
  binary PDF; in practice always use `-o file.pdf`).
- **Format auto-detect** from extension: `.md` / `.markdown` → Markdown,
  `.json` → pretty-printed, `.pdf` → pass-through, anything else → plain
  monospace text.
- **Markdown features supported**: `# / ## / ###` headings, paragraphs,
  `- item` and `1. item` lists (with nesting), ` ``` fenced code `,
  `> blockquote`, `---` horizontal rule, **bold**, *italic*, `inline code`,
  `[link text](url)` → text only, pipe tables with header + separator row.
- **Layout**: A4 (210 × 297 mm), 18 mm margins, Helvetica 10 pt body,
  Courier 9 pt for monospace / preformatted / code. Long content
  paginates automatically (ReportLab platypus).

## One-page infographic and poster rule

An A4 one-page infographic is a poster, not a notebook page. Design it for
reading at **1–2 metres**, not for a person holding it 30 cm from their face.
The best use of the page is therefore readable hierarchy and visual
compression, not maximum text density.

- Establish one dominant message and a small number of secondary zones.
- Use short labels, phrases, diagrams, arrows, and comparisons; do not pour a
  transcript or paragraph-heavy notes onto one page.
- Set type for the viewing distance first. If the content does not fit at a
  distance-readable size, cut or restructure the content; never solve the
  problem by shrinking the type until it becomes notebook-sized.
- Keep the page visually full with meaningful structure, not with tiny copy:
  large nodes, clear grouping, generous separation, and an obvious reading
  path are productive uses of space.
- Acceptance test: print or render the final A4 page at 100% and read it from
  1–2 metres in normal light without zooming, leaning in, or handling the
  sheet. A failed distance-read is a content/layout failure, not a reason to
  reduce the type size.

### Examples

```bash
# Markdown source -> A4 PDF
./printable.py --title "Trip Notes" trip_notes.md -o trip.pdf

# Plain text -> A4 PDF
./printable.py report.txt -o report.pdf

# JSON pretty-printed as A4 PDF
./printable.py --format json data.json -o data.pdf

# Pipe stdin
echo "Hello A4" | ./printable.py -o hello.pdf

# Pass through a PDF (skip rendering)
./printable.py already.pdf -o same.pdf
```

## install_reportlab.sh — one-time setup

For each new sender host, run `bash install_reportlab.sh`:

1. Try `apt install -y python3-reportlab` first (clean, no PEP-668 friction).
2. Fallback to `pip3 install --user --break-system-packages reportlab` on
   hosts where the apt package isn't available.
3. Last resort: bootstrap pip via `get-pip.py` then install.

After install, verify with `python3 -c 'import reportlab; print(reportlab.Version)'`.

## Macbook watcher (the receiver)

Lives at:
- `~/PrintQueue/print_watcher.py` (live, running as LaunchAgent
  `com.bruno.printwatcher`)
- `~/Library/LaunchAgents/com.bruno.printwatcher.plist` (the agent)
- `~/AI/tailscale-network/devices/macbook/scripts/print_watcher.py` (repo)
- `~/AI/tailscale-network/devices/macbook/launchd/com.bruno.printwatcher.plist` (repo)

Three folders under `~/PrintQueue/`:
- `inbox/` — where senders drop `.pdf` files
- `done/` — successfully printed (file kept for audit + dedupe)
- `failed/` — rejected; `.reason.txt` sidecar explains why

The watcher polls every 1 s, debounces partial uploads via mtime+size
stability (2 polls), and runs `lp -d HP_DeskJet_2700_series <file>` for
each settled file. Watcher is a strict pass-through — no text conversion,
no PDF rewriting, no driver fiddling.

## Known limitations

- **Watcher only runs when macbook is awake and at home.** When the laptop
  is closed or away, files accumulate in `inbox/` and print when both wake
  up. Acceptable because the fleet sender knows when they expect the
  output.
- **Printer must be on.** If `lp` returns "not accepting requests", the
  file goes to `done/` (because lp accepts the job) but the actual print
  waits for the printer. Check the output tray.
- **One-way**: macbook → printer. There is no return channel for print
  status. If a job fails to print, the file stays in `done/` but the
  page never comes out. Fix the printer, then `cp` the file back into
  `inbox/` to retry.
- **Until the NiPoGi home-server VM lands** (delivery 2026-07-27), fleet
  printing depends on macbook being online. The long-term plan is a Linux
  CUPS queue in that VM. See
  `~/AI/tailscale-network/global/plans/2026-07-24-print-pipeline-and-subnet-router.md`.

## Pitfalls

1. **Don't drop a `.txt` file.** The watcher rejects it. Convert with
   `printable.py` first.
2. **Don't scp a PDF without first trusting macbook's host key** (one-time
   per sender). Run `ssh-keyscan -H macbook.spaniel-orfe.ts.net >> ~/.ssh/known_hosts`.
3. **Don't edit a file while it sits in `inbox/`** — the watcher will see
   the size change, reset its stability counter, and not print until it
   settles again.
4. **Don't queue more than ~10 large PDFs at once.** The watcher is
   single-threaded; very large PDFs (50+ pages) print one at a time and
   the others wait.
5. **Don't expect a feedback signal.** When the printer is off, files go
   to `done/` (because `lp` accepts them) but no paper comes out.
6. **Don't use `cupsfilter` or other PDF re-renderers on macbook.** The
   watcher is a pass-through; re-rendering adds a chance of corrupting
   the layout the sender chose.

## Related

- `~/AI/tailscale-network/devices/macbook/RULES.md` — "Printing — local
  queue + drop-folder for fleet" section documents the receiving side.
- `~/AI/tailscale-network/global/plans/2026-07-24-print-pipeline-and-subnet-router.md`
  — the long-term Linux CUPS plan in the home-server VM.
