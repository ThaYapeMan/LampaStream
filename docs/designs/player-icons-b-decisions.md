# Option B player icon decisions

- Copy `icon-size-sketch.png` byte for byte to the requested `player-icons-size-option-b.png`: the named reference was absent, and the supplied untracked sketch's right-hand column exactly matches the approved dimensions. Preserve the original untracked sketch.
- Retain `rounded-lg` at both sizes: its existing measured 10 px corner radius matches the option B sketch and keeps the established box style.
- Keep the Follow player dropdown glyph at 17 px: it is a compact picker rather than a Players list row.
- Keep the Now Playing LightTiming diagram glyph at 18 px in its 36 px tile: it is a compact timing diagram rather than a list row or detail header.
- Keep PlayerGlyph's default at 17 px and make the compact picker size explicit: future default changes must not silently enlarge the picker.
- Preserve existing flex alignment, gaps, padding, timing pills and name truncation: the layout already centres content beside a larger tile without structural changes.
- Save additional LMS detail screenshots with the `players-icons-b-lms-` prefix: inspect the Lyrion waveform while preserving all earlier screenshots.
- Use the same six player fixtures and local API/websocket routes: compare sizes without contacting owner devices.
- Run browser tests with one worker: avoid the hold-repeat timing contention observed during the previous task without changing test thresholds.
- Save complete command output in a text appendix: retain all test results, skips and warnings without truncation.
- Allow the natural flow growth caused by larger tiles: two-line list rows become 64 px (previously 60 px), and the header becomes 56 px (previously 48 px), while padding and gaps stay unchanged.
- Exercise long names at 1400 px and 390 px after the six-player captures: verify ellipsis and absence of horizontal overflow without altering the requested screenshots.
- Use two workers for the complete unit/component suite: keep the full suite while reducing host contention.
