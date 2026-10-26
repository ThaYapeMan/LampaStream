# Player icon decisions

- Copy the four SVGs byte for byte into `web/src/assets`, and track the supplied originals: Vite owns the UI asset pipeline and the artwork remains reviewable.
- Use alpha masks for all four supplied SVGs: inspection found only monochrome artwork, including implicit black in SqueezeRadio.
- Keep waveform identity for all managed LMS receivers using the supplied Lyrion SVG waveform: these are LampaStream's own analysis players, regardless of their advertised name.
- Recognise external LMS players by case-insensitive `modelname: yeney`, without requiring a ` (Sonos)` name suffix. YeneY can omit that suffix because the icon already identifies Sonos. An explicit `sonos_room` link is also sufficient evidence; a name containing “Sonos” alone remains insufficient. Managed receivers and the exact case-insensitive `LampaStream LMS` name retain precedence because our own yeney-player reports the same model.
- Match metadata MACs case insensitively without changing request identities: LMS CLI continues to receive raw MAC addresses.
- Discover configured LMS hosts once per mounted view and retain generic icons if discovery fails: avoid adding polling or device probes for decorative UI.
- Reuse the mapping in the Players list/header and Now Playing timing diagram, and add it to the Follow player picker named in the task: other text-only labels remain text-only.
- Preserve existing receiver tile colours and all tile geometry: this retains the established appearance of managed receivers.
- Replace the sole legacy LMS artwork reference (the raster waveform) with the supplied vector Lyrion waveform: this preserves the explicit waveform exception while replacing the Lyrion artwork. Replaced locations: Players list rows and player detail header. No separate source/server logos existed in this checkout.
- Use fixture-only Playwright API/websocket routes with a reserved `.invalid` host: screenshots never contact the owner's LMS or devices.
- Capture the desktop list and selected Sonos detail panel together in each requested screenshot; assert geometry for every fixture's detail panel before capture. Save additional LMS detail screenshots to inspect the Lyrion logo.
- Keep LMS model metadata when a saved timing has a friendly display name: aliases must not erase player identity. Sonos classification is independent of the discovered name and timing alias.
- Quote CSS mask URLs: Vite inlines small SVGs as data URLs whose embedded quotes otherwise invalidate CSS.
- Limit the final full frontend run to two workers: reduce contention while retaining every unit and component test.
- Use the Lyrion waveform in the shared glyph renderer so future managed player glyphs also use the supplied asset; leave the now-unused tracked PNG intact to avoid an unrelated asset deletion.
- Use LMS discovery metadata because this checkout has no Sonos room registry; accept an explicit `sonos_room` link if supplied by discovery.
- Start Vite directly on localhost for browser checks: the existing 15-second npx web-server timeout expired on this filesystem; keep the repository timeout unchanged.
- Scope the existing managed-tile colour regression to managed tiles: generic glyphs now also expose a test marker, and the new tests cover their theme colours separately.
- Save complete raw validation output in a text appendix: retain every backend test, skip reason and warning without truncating the report.
- Rerun the full browser suite with one worker after a parallel hold-repeat failure passed in isolation: all 65 tests then passed, with the original failure retained in the raw appendix.

## Suffix-free identity audit

- `web/src/lib/playerIcons.ts`: the sole production suffix check, now removed.
- `PlayerGlyph` shares this mapping with the Players list/detail header, Follow picker and Now Playing `LightTiming` diagram; artwork, option B dimensions and colours are unchanged.
- `PlayersDetail.buildPlayerRows` joins saved timing aliases to discovery by case-insensitive MAC. `LightTiming` also joins by MAC and retains model metadata when using an alias. No name normalization is needed.
- `usePlayerMetadata` and `/api/lms/players` retain discovery model metadata. The API excludes managed receivers by registered MAC, regardless of name/model.
- `lms_status._parse_players` and `_parse_status` preserve the reported name verbatim. Storage keys timing entries by MAC; aliases are display text.
- `lms_follower.LmsFollower` and `LmsSyncGroupObserver` match notification targets and group peers by MAC. `PlayerManager` resolves display names from status; Couplings resolves the follow label by MAC. None inspects the Sonos suffix.
- Fixtures retain suffixed cases and add Study, MBR and Sonos Port without suffixes, including saved aliases and both light/dark browser verification.
