# Music colours and transitions

Round 1 connects the existing sustained-energy tracker and adds a shared palette
library. Rhythm detection, onset routing, DSP algorithms, the delay buffer and timestamped
AirPlay scheduling are unchanged.

## Sustained energy

Each canonical PCM block feeds a session-owned tracker before analysis. Its
short/long EMA ratio follows changes in section loudness. Silence holds its last
value; a new coupling starts a new tracker. Now Playing displays this value next
to the energy blend. Existing Energy Profiles using `sustained` now receive it;
the original fallback remains available for an absent measurement.

## Palette library

Palettes contains twelve starter palettes: Sunset, Ocean, Neon, Monochrome,
Ember, Candlelight, Glacier, Forest, Pastel garden, Lavender, Party and Electric.
Create, edit, duplicate or delete a palette here. A palette referenced by an
effect, rule or manual choice cannot be deleted. The preview uses the active
zone's channel positions and the existing floor-plan component, without sending
anything to lamps.

A palette has 2–8 ordered hex-colour stops with positions from 0 to 100%. Missing
edge stops repeat the nearest colour. Sampling interpolates in OKLab with
`t^1.5 / (t^1.5 + (1-t)^1.5)`, using a cached, precomputed 1,024-entry lookup.
Rotation is measured in cycles per second, independent of the frame rate.

Hue's existing channel API exposes positions but no individual gamut. Gamut C
is therefore the default. Chromaticities are uniformly compressed towards D65
white with one positive affine factor fitted to the entire sRGB primary
triangle. This avoids nearest-edge clipping which would merge different saturated
colours; brightness is retained. Injectivity applies to chromaticity before lamp
quantisation; colours closer than a lamp's finite resolution cannot be promised
to look different. White remains white.

| Effect | Palette sampling |
| --- | --- |
| Band colours and extensions | Ordered frequency-band positions; existing band playback and advancement remain intact |
| Gradient, solid, monopulse | Centroid/value; the existing scene retains brightness |
| Swirl | Polar x/y position and z |
| Wave and splotch | x position with a y/z spatial contribution |
| Pulses and flashes | Existing scene's hue/value progression; onset and envelope remain intact |
| Fireworks | Distance in x/y/z; the existing bursts retain their timing |
| Spectrum RGB and extensions | Bass/mid/high mix three ordered palette samples, preserving the existing envelope |
| None | Black, with no colour sampling |

Schema 2 converts each legacy `band_colours` list into a deterministic palette,
and the four legacy gradient names into curated palettes. Legacy fields and
original lists remain unchanged in configuration and API responses. Migration is
atomic, backed up, validated and idempotent. The former gradient constants also
remain available for legacy callers. The new perceptual interpolation is an
intentional visual change.

## Album art

Choose Album art in an effect or as a manual track palette. LMS metadata uses
the followed player's CLI `status`/subscription tags `adglcK` for album, genre,
cover ID and remote artwork. A cover ID produces the LMS artwork URL. AirPlay
cover art and genre share the existing sole metadata reader; `ssnc/PICT` carries
binary artwork, `core/asgn` textual genre and `core/gnre` a one-based ID3 genre
index. Unsupported numeric genres retain their ID3 number as a raw tag and map to `other`. The installer and default
receiver template enable `include_cover_art = "yes"`; runtime activation does
not edit this setting or restart the receiver to enable artwork.

Artwork parsing and quantisation run off the light loop. Images are bounded to
8 MB and 16 million pixels and reduced to 192 × 192 before median-cut extraction.
The owner's two-pass extraction, HSV merge thresholds, share accounting,
farthest-point rescue, dark-pixel mask and punchy LED correction are implemented.
Circular hue distance is normalised by its maximum half-turn to 0–1 before the
specified weighting. Deterministic ties use RGB order.

The common eight-stop limit also applies to extracted palettes. Without a
background, the four strongest colours retain proportional bands and softened
boundaries. With a dominant background, the two strongest accents have evenly
spaced sections, a 40% flat centre and background between them. This fits all
flat regions and boundary stops within the model. Single-colour artwork repeats
one colour at both edges.

A session cache retains 128 image hashes and 128 artwork URLs. Identical artwork
is not extracted again. Failed artwork retains the currently displayed palette
and logs once per failed image/URL; it never turns the lights off.

## Genre privacy and rules

Music settings contains the Last.fm opt-in switch, API key, editable tag mapping,
genre rules and transition controls. Last.fm is off by default. When off, no
track or artist is sent. When enabled, the user-supplied API key is stored only in
configuration; normal settings responses redact it. Configuration backups contain
secrets and require the same care as the existing bridge credentials.

A recognised file tag takes priority. Otherwise Last.fm `track.getTopTags` is
tried, then `artist.getTopTags`. Calls are separated by at least 1.1 seconds,
have a one-second network timeout and a 1.2-second task limit, and run away from
the render loop. Successful track/artist results have a 24-hour TTL; empty results
have five minutes. A rate-limit response backs off for five minutes, other errors
for one minute. The bounded cache holds 512 results. Request URLs, API keys and
error bodies are never logged. Last.fm attribution and terms are linked in the UI.

The fixed genres are house, techno, trance, drum & bass, electronic/ambient,
hip-hop, R&B/soul, pop, rock, jazz, classical and other. Raw tags and the chosen
genre are shown on Now Playing. Default mappings live in `genres.py`; the editable
mapping table in Music settings overrides them. Rules apply a palette and/or an
Energy Profile at track change. Now Playing's manual choices persist per coupling
and independently take priority until Clear manual choices is pressed. Rule
choices do not rewrite the coupling's base Energy Profile. Now Playing reports
the effective profile, and edits to its effects or blend settings refresh
rendering without reactivating the coupling.

## Smooth changes

Effects, palettes, Energy Profiles and new artwork blend over 0.7 seconds by
default, configurable from 0 to 2 seconds. Crossfade blends old/new RGB. Through
black caps the old channels to `1-2w` then the new to `2w-1`. Through white raises
the old channels to at least `2w` then the new to at least `2(1-w)`.

Both scenes render during a transition. A new change during a transition starts
from the frame actually sent to Hue, so it does not jump. The transition clock
starts when the scheduled output first samples the scene, not during analysis
or delay-buffer fill. Existing 30 Hz output, early-tap play times, delay buffers,
Hue stream ownership and recovery remain unchanged. Strip transitions and strip
effects are deferred to the later phase requested by the owner.

## Processing budget

The isolated processing benchmark exposed the existing loudness biquad's cost of
repeated tiny NumPy operations on stereo arrays. Execution now uses scalar floats
per channel with the same coefficients, direct-form-II recurrence and operation
order. A four-channel deterministic fixture proves bit-for-bit output and filter
state across chunk boundaries. This is an implementation optimisation, not a
change to the loudness or rhythm algorithms.

## Design and references

The four HTML mockups in `docs/designs/` were added before implementation. The
implementation uses existing Cards, Buttons, confirmation dialogs, sidebar,
floor-plan preview and semantic theme tokens. Lists and related controls are
grouped; destructive actions require an inline dialog; labels describe actions.
Controls have adequate touch targets and columns stack on phones. System light
and dark appearance use the same semantic tokens. New pages are lazy-loaded to
keep the main bundle within the existing build size threshold.

No LedFx or aubio source or package was opened, copied, translated or added.
Implementation follows the owner's specification and these published references:

- [OKLab mathematics, public domain/MIT](https://bottosson.github.io/posts/oklab/)
- [Pillow median-cut API](https://pillow.readthedocs.io/en/stable/reference/Image.html#PIL.Image.Image.quantize)
- [Lyrion CLI database tags](https://lyrion.org/reference/cli/database/)
- [Lyrion compound queries](https://lyrion.org/reference/cli/compoundqueries/)
- [ID3v2 genre numbering](https://id3.org/id3v2.3.0)
- [Last.fm track tags](https://www.last.fm/api/show/track.getTopTags)
- [Last.fm artist tags](https://www.last.fm/api/show/artist.getTopTags)
- [Last.fm API terms](https://www.last.fm/api/tos)
- [Apple HIG layout](https://developer.apple.com/design/human-interface-guidelines/layout)

Installed metadata identifies Pillow as MIT-CMU and HTTPX as BSD-3-Clause; both
are permissively licensed dependencies, recorded in THIRD_PARTY_NOTICES.md. Hardware colour
appearance and sender-specific genre/artwork availability require the owner's
normal installation checks; agents do not deploy to or access an LXC.
