# Jimmy 1.0.2 — for the website (2026-11-04)

Short brief for the site's changelog, download and docs pages. Source records:
`DECISIONS-AND-WHY.md` D63–D65. Every number below is measured.

**Download:** Releases → `v1.0.2` (`Jimmy-Setup-1.0.2.exe` + `.sha256`). From 1.0.1 on, installed
copies update themselves: they check GitHub Releases 10 min after start and every 6 h, verify the
SHA-256, and install on a click or at the next start, keeping data and settings. Switch:
Settings → "Update Jimmy automatically". 1.0.0 users install 1.0.1 or later once, by hand.

**Changelog, 1.0.2**
- **Jimmy repairs itself.** Say "Jimmy, what's wrong with the camera?" and it checks itself and
  says what it found. Say "you can use the camera, fix it" and it repairs what it can on the spot,
  without a restart: its own setting, a stuck camera, the right camera. For Windows' privacy
  switch, which only you can change, it opens the right Settings page.
- **The camera works.** The webcam took 16.5 s to open through Windows Media Foundation on the
  test laptop. It now opens in 0.5 s, with a DirectShow fallback.
- **No more flashing command windows at start.** Every helper process starts hidden.
- **A gentler start.** Jimmy runs at below-normal priority while it loads. The camera starts 15 s
  after voice, and search indexing 30 s after.
- **See what Jimmy is doing.** A Status dock (the pill's Status button, or "Jimmy, show status")
  shows:
  - listening, and for how many seconds you can talk without saying "Jimmy";
  - the camera;
  - Jimmy's own CPU and RAM, with a one-minute graph;
  - the update, with download % and **Update now**;
  - capture, and the AI model.

  The pill itself shows a countdown ring, the camera, a call, and a download badge.
- **A smoother floating UI.** Streamed answers no longer redraw the overlay for every word, and
  hover handling and the "Thinking…" animation got lighter.

**Changelog, 1.0.1 (2026-11-02)**
- Auto-update, plus releases published by CI once a clean-machine test passes.
- The camera is no longer reported "in use" by an app that crashed or by Jimmy itself.

**Docs page, "If something's off"** (one paragraph): ask Jimmy. "What's wrong with the camera?"
gets a diagnosis; "fix it" gets a repair. Jimmy never changes Windows' own privacy settings
itself; it opens the page.
