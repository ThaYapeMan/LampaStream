# HueSync — analysis layer options (v2)

*Replaces v1. v1 concluded that all usable libraries were GPL and the only route
was spawning subprocesses. That was wrong: there are permissively licensed
options, and more importantly the algorithms themselves are not restricted at
all.*

---

## The licence distinction that actually matters

Not "commercial vs open source" — commercial software builds on open source
constantly. Windows shipped a TCP/IP stack derived from BSD for years, and
Microsoft was entitled to do that because the **BSD licence permits it**.

The real split is **permissive vs copyleft**:

| Licence | Can be linked into MIT code |
|---|---|
| MIT, BSD, ISC, Apache 2.0 | ✅ yes |
| GPL, LGPL (with conditions), AGPL | ❌ not without relicensing |

And a second distinction that matters just as much:

**Algorithms are not copyrightable. Implementations are.**

Superflux onset detection is a published paper (Böck & Widmer, 2013). The
spectral flux method, mel filterbanks, autocorrelation tempo estimation — all
published research, freely implementable. What a licence covers is *someone's
particular code*, not the method.

librosa's own Superflux example is roughly twenty lines: mel spectrogram,
lagged difference, maximum filter, peak picking. Reimplementing that from the
paper in MIT-licensed code is entirely legitimate. This is exactly what LedFx
did — their melbank coefficients are documented as "based on Scott's audio
reactive led project", reimplemented rather than copied.

---

## Permissively licensed options

### librosa — ISC

The strongest candidate, and it was wrongly dismissed in v1.

- **Licence: ISC.** Permissive for linking, distribution, modification and
  sublicensing. Compatible with MIT.
- Provides `librosa.onset.onset_strength`, `librosa.onset.onset_detect`,
  `librosa.beat.beat_track` (beats *and* tempo in one call), mel spectrograms,
  STFT, CQT, spectral centroid, and the Superflux algorithm
- Very widely used, well documented, actively maintained

**The catch is not the licence but the design.** librosa is built for offline
analysis of complete signals on NumPy arrays, not streaming. Two consequences:

- `beat_track()` estimates tempo globally over whatever signal it is given. For
  real-time you would feed it a rolling window (say the last 5-10 seconds) and
  re-estimate periodically. That works, but it is not a causal beat tracker in
  the way BTrack is.
- It pulls in NumPy, SciPy and (verify this) numba. On a 2-vCPU LXC already
  running squeezelite and cava, that is a real cost — check the dependency
  tree and cold-start behaviour before committing.

**Verdict:** usable, and the licence is fine. Best suited to periodic
re-estimation (tempo, key) rather than per-frame work.

### pyAudioAnalysis — Apache 2.0

Feature extraction, classification, segmentation. Permissive licence. Broader
in scope than needed here and less focused on real-time musical features than
librosa. Worth knowing about, unlikely to be the first choice.

### NumPy / SciPy — BSD

The DIY route, and not to be underestimated. Everything HueSync actually needs
per frame is short:

- **Spectral flux**: sum of positive differences between successive spectra
- **Peak picking**: rolling mean + standard deviation, with a cooldown
- **Spectral centroid**: weighted mean of bin index by magnitude
- **Mel-like band grouping**: index arithmetic on cava's already log-spaced bars
- **AGC / EMA**: already implemented as `BandNormaliser`

None of that needs a library. It is a few dozen lines, fully under your own
licence, with no dependency risk and no cold-start cost.

---

## Copyleft options, and how they can still be used

### aubio — GPL-3

C core with Python bindings, explicitly built for real-time audio labelling:
onset, pitch, beat, tempo. Used by LedFx.

Cannot be imported into MIT code. **But it ships CLI tools** — `aubioonset`,
`aubiotrack`, `aubiopitch` — and running a separate program does not make your
code a derivative work. HueSync already does exactly this with squeezelite
(GPL) and cava.

### BTrack — GPL-3

Purpose-built causal real-time beat tracker from Queen Mary University of
London, with published papers behind it. Small API. Same subprocess caveat as
aubio, though it is primarily a library rather than a CLI tool, which makes the
subprocess route less natural.

### Essentia — AGPL

Comprehensive C++ MIR library. AGPL is stricter still. Not worth the trouble
given the alternatives.

### madmom — mixed

Neural-network based, best-in-class accuracy, but designed for offline
multi-core batch processing. Too heavy for this hardware regardless of licence.
Verify the licence per module if ever reconsidered.

---

## Recommendation for a 2-vCPU LXC

The constraint here is CPU, not licensing. Ranked by cost:

### 1. Own implementation (NumPy or plain Python) — start here

Spectral flux onset detection on cava's existing bars, as already specced.
Zero new dependencies, zero licence questions, negligible CPU. Fills `onset`
and `onset_strength`.

Add spectral centroid and peak isolation at the same time — both are a handful
of lines on data already in hand.

### 2. librosa for periodic estimation — if tempo is wanted

If effects start needing real tempo (beat-locked palette changes, double-time
and half-time controls), add a `LibrosaAnalyser` that runs `beat_track()` on a
rolling buffer every few seconds rather than per frame. Licence-clean, and the
cost is bounded because it does not run at frame rate.

This requires the direct PCM tap (reading `/dev/shm/squeezelite-<mac>`
alongside cava), since librosa needs samples, not bars.

### 3. aubio as a subprocess — if 1 and 2 both fall short

`aubiotrack` / `aubioonset` fed from the PCM tap, output parsed line by line.
Same pattern as cava, same licence boundary. Only worth it if the quality
difference proves to matter in practice.

---

## What this means for the interface

Unchanged from v1 — the point of the layering is precisely that this decision
stays reversible:

```python
class Analyser(Protocol):
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    def latest(self) -> AudioFeatures: ...
```

- `CavaAnalyser` — cava bars + own flux onset detection *(stage 1)*
- `LibrosaAnalyser` — adds beat/tempo from a rolling PCM buffer *(stage 2)*
- `AubioAnalyser` — subprocess-based *(stage 3, only if needed)*
- `NullAnalyser` — scripted features for tests

Fields a backend cannot fill stay `None`; effects must degrade gracefully when
`beat` or `tempo` is unavailable.

## Sources

- librosa licence (ISC, permissive linking/distribution/modification):
  https://cloudsmith.com/navigator/pypi/librosa
- librosa onset_strength / onset_detect / beat_track:
  https://proceedings.scipy.org/articles/Majora-7b98e3ed-003.pdf
- Superflux onset detection (Böck & Widmer 2013) as implemented in librosa:
  https://librosa.org/doc/latest/auto_tutorials/03-advanced/plot_superflux.html
- pyAudioAnalysis (Apache licence):
  https://www.ncbi.nlm.nih.gov/pmc/articles/PMC4676707/
- aubio: https://github.com/aubio/aubio
- BTrack (GPL-3, causal real-time beat tracking):
  https://pypi.org/project/btrack-beat-tracker/
