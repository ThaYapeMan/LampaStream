# GRID-01 send-back 5: memory findings

Status: canonical ingress, memory bounds and local tracker repair are implemented.
The 5d chapter defines current owner-reviewed acceptance; verification and CI
outcomes are recorded in the 5d report. Target validation remains the owner
procedure. Evidence here is local/offline; no owner LMS or LAN was accessed.

## Field evidence

On 2026-11-11 at 23:11 and 23:17, LXC 112's 4 GB memory cgroup killed the
library survey on Prince, “1999”, LMS track 45300: ALAC, 96,000 Hz, 16 bit,
375.7 seconds, 2,880 kbps. The recorded kernel message was:

```
Memory cgroup out of memory: Killed process 575914 (python) total-vm:6099800kB, anon-rss:4072356kB … oom_memcg=/lxc/112
```

The old decoder mixed to mono and retained the native analysis rate. This
violated the 48 kHz stereo canonical contract and made DSP memory rate-dependent.
A mono mix also attenuates hard-panned attacks and cancels opposite polarity.

## Profile and changes

The baseline is origin/master `03d70f98c50953d31a09ae1e1833229392e9cde6`.
A generated six-minute stereo FLAC contains 80 Hz decaying clicks every half
second. Generation writes one second at a time. Fresh subprocesses use one BLAS
thread; `resource.getrusage(RUSAGE_SELF).ru_maxrss` measures the analyser process.
No source audio is committed. Commands, raw outputs and comparison JSON are
retained in `.test-cache/grid-01-sendback-5/` and the final report.

A tracemalloc snapshot at the largest active inverse-FFT allocation on the
44.1 kHz baseline showed these top five live allocations:

| Allocation location | Live size | Meaning |
| --- | ---: | --- |
| scipy/fft/_duccfft/basic.py:95 | 341 MiB | inverse FFT result/workspace |
| numba/np/ufunc/dufunc.py:303 | 171 MiB | power-spectrum ufunc output |
| librosa/feature/rhythm.py:175 | 163 MiB | windowed tempogram input |
| numpy/_core/_methods.py:132 | 60.6 MiB | whole-file mono array |
| pathlib.py:1020 | 1,329 KiB | original compressed bytes |

Traced peak allocation fell from 1,138,962,222 bytes in the warmed baseline
profile to 318,216,644 bytes in the final candidate (the latter also includes
lazy imports). Tracing changes RSS, so the table below uses separate untraced
runs for both implementations.

The largest waste was the **tempo estimator's** duration-wide eight-second
windowed autocorrelation, beyond the expected full STFT and low-band FFT.
Computing just the onset envelope did not remove it. The candidate accumulates
the same default librosa tempogram mean in 256-frame blocks and passes its tempo
and the once-computed median-aggregated onset envelope to beat tracking. A direct
regression checks these bounded computations against librosa's defaults.

Other changes:

- Native libsndfile decode streams 16,384 frames at a time through the existing
  `AudioCanonicalizer`; mono duplication and soxr belong to that canonicalizer.
  FFmpeg preserves native channels/rate and writes float PCM to a temporary file,
  avoiding whole-output `communicate()` buffers. Head FFmpeg decode uses `-t`.
- Canonical stereo PCM is preallocated once. CLI input is mapped read-only;
  a seekable buffer view avoids the whole-file `BytesIO` copy. Original-byte
  SHA-256 and source rate/channel provenance remain available.
- Per-channel low-band envelopes combine by maximum. Filtering and RMS stay
  float32; squaring uses the filter buffer in place. There is no mono accent mix.
- Beat positions alone use canonical mid. Its mel STFT runs in blocks without
  whole-signal padding. The head's separate 11,025 Hz resampling is removed; its
  STFT runs directly on canonical samples, also in bounded blocks.
- Only the needed low-band correlation lags are computed with dot products,
  avoiding the duration-wide FFT. Imported/JIT caches remain unavoidable fixed
  overhead rather than duration-dependent scratch.

## Six-minute memory results

| Native rate | Baseline peak RSS | Candidate peak RSS (CI regression run) | Outcome |
| --- | ---: | ---: | --- |
| 44,100 Hz | 1,306,072 KiB | 463,450,112 bytes | 720 beats; candidate passes |
| 96,000 Hz | 5,088,692 KiB | 464,592,896 bytes | 720 beats; candidate passes |
| 192,000 Hz | 2,097,952 KiB | 467,308,544 bytes | baseline fails “Insufficient beats”; candidate produces 720 |

Baseline runs had an 8 GiB address-space ceiling to avoid an uncontrolled host
OOM; none was killed. An earlier 3 GiB ceiling failed at 96 kHz allocating a
1.51 GiB FFT array; its partial RSS is not the successful baseline figure.
At 192 kHz the baseline's peak is a failed analysis, not a valid grid measurement.
Candidate beats and bass drum flags agree across all three rates within 2 ms; each
peak is below 1,000,000,000 bytes. The `grid_memory` marker is registered and is
not excluded from normal local or CI suites.

## Process boundary and failure

Production LMS already runs a separate `nice -n 10` analyser subprocess. It does
not run `analyse()` in the service. After fixed-size lazy-import/JIT warm-up for full grids, the
CLI sets Linux `RLIMIT_AS` to:

```
min(2 GiB, imported virtual size + 384 MiB + duration_seconds * 1 MiB)
```

A lower inherited hard limit is respected. Head duration is capped at 60 seconds.
The observed six-minute worker ceiling was 1,576,656,896 bytes; this varies with
the imported VM floor and is not an RSS claim. The public Python function does
not set its caller's process-wide resource limits.

The CLI catches allocation/OS/probe/decode failures, logs
`Grid analysis unavailable; retaining tracker: <type>: <reason>` and exits 1.
The unchanged LMS adapter logs `Library grid unavailable ...; retaining live
analysis` and keeps the tracker. A forced real allocation failure regression
asserts exit 1, no grid output and the reason in stderr, rather than a signal.
Head workers skip the librosa warm-up so a cold cache cannot consume their
30-second provisional deadline. A fresh-cache regression checks this.
The bound also exposed the head's 162 MiB promoted FFT workspace; its block
conversion is necessary for provisional startup, not just full-file memory.

## Musical acceptance: unresolved

Existing private-fixture expectations were not relaxed. Final before/after
comparison of corresponding beat indices:

| Fixture | BPM before → after | bass drums before → after | Changed flags | Maximum beat shift |
| --- | --- | --- | ---: | ---: |
| Mau P | 127.998025 → 127.998246 | 653 → 657 | 6 | 1.998 ms |
| UDKM | 129.985879 → 129.970806 | 981 → 298 | 683 | 11.745 ms |
| Lou Rawls | 77.133862 → 77.054795 | 184 → 200 | 18 | 459.900 ms |

All beat counts remain 814 / 1053 / 215, respectively. The required ±1 ms
invariance fails on 814 / 1015 / 193 corresponding beats. Lou is expressive;
its large maximum is a changed tracker position, not a rigid phase shift.

A diagnostic canonical **mono** accent envelope (not used in production code)
still gives 654 / 301 / 184 bass drum flags. Thus the regression is not explained
solely by the new max channel combination: canonical-rate tracker hops, low-band
window quantisation and the existing section coherence gate are also sensitive
to the conversion. No musical thresholds were retuned to force the old counts.
The required canonical implementation and memory regressions are reviewable,
but this candidate must not be represented as accepted or deployed until the
musical regressions are resolved with the existing assertions intact.

## Owner field procedure after acceptance

On the supported target, update the checkout and run the standard installer:

```sh
git pull --ff-only origin master
sudo ./scripts/install-lampastream.sh
sudo ./scripts/install-lampastream.sh --check
```

Play Prince “1999”, LMS track 45300 (96 kHz ALAC), on the Sonos Port. Expect
`Library grid ...  BPM` within the usual analysis time, a 48,000 Hz grid with
`source_sample_rate=96000`, and no analyser/service kill in
`journalctl -u lampastream` or the host's `dmesg`. No owner device was accessed
for this local work. This procedure is pending musical acceptance; do not deploy
the current failing candidate on the strength of the RSS results alone.

## Send-back 5b: corrected control and isolated root cause

The owner clarified that the 982-flag 48 kHz UDKM control used FFmpeg 6.1.1's
**default swr**, not soxr:

```sh
ffmpeg -i armand…m4a -ar 48000 -c:a flac out.flac
```

The owner's soxr control produces 301 flags with unchanged `03d70f9`, matching
the local reproduction. Local baseline source SHA-256 is
`f51f454d26e1c4d4e9e8de1d63988e0b831d73f1d749fd0b73a234e578b771e9`,
identical to `git show 03d70f9:src/lampastream/grid/analyser.py`.

The single confirmed cliff is in `kick_evidence`: a section-wide attack-offset
MAD above 20 ms returned three zero arrays before classifying any individual
beat. The owner's whole-track measurements were 18.1 ms (swr), 18.4 ms (soxr),
and 18.9 ms (native), with per-section values crossing the cut. On/off energy,
reference and level were otherwise essentially unchanged. The analyser's later
phase correction also depends on positions with bass drums, amplifying the veto.

The candidate now computes offset MAD in centred 17-beat windows. Weight is
1 up to the old 20 ms limit, then decreases continuously as
`1/(1+max(0, MAD/.02-1)**2)`. These weights affect the marginal on-energy median;
no whole-section veto remains. Existing strong-evidence rules and thresholds
are unchanged. The exact source diff is recorded in the send-back 5b report.

### Ingress and refactor probes

- A 60 s, 44.1 kHz stereo 50 Hz sine yields exactly 2,880,000 canonical frames.
  Candidate and whole-file HQ soxr PCM and low-band envelopes are **bit-for-bit
  equal**. Across 161 native chunk boundaries, maximum extra attack energy is 0.
  Both have a maximum boundary attack of 0.0467323065, also the interior maximum;
  the nonzero RMS-rise pattern is the shared steady-sine/filter phase response.
- A 300 s native FLAC and its ALAC conversion each yield exactly 14,400,000
  canonical frames: **zero** dropped/duplicated samples.
- All three private fixtures are bit-for-bit equal to whole-file HQ soxr,
  including canonical lengths 18,298,656 / 23,340,802 / 8,142,720 frames.
- Individually restoring the full tempogram, float64 filtering, whole-file
  decode/resampling, whole-signal centre padding, or full mel computation leaves
  the pre-fix candidate results **identical**: Mau P 127.998246 / 814 / 657;
  UDKM 129.970806 / 1053 / 298; Lou 77.054795 / 215 / 200 (BPM/beats/flags).
  Those memory improvements are therefore retained.
- Unmodified `03d70f9` run on identical canonical **mono** PCM exactly matches
  the candidate with float64 mono evidence: 127.998398 / 814 / 654;
  129.986937 / 1053 / 301; 77.054795 / 215 / 184. No memory-refactor defect
  explains the remaining differences. The decoder's native-rate mono differs
  from the old ALAC pipe only by its expected constant downmix gain.

Continuity/sample-count regressions and near-threshold/locality coherence
regressions are added. Private tests compare native canonical, swr and soxr
routes, each with and without deterministic -90 dBFS RMS Gaussian dither. The
new strict timing tests pin the original `03d70f9` beat timestamps without audio.
The full outputs and final robustness counts are in
`/home/codex/src/reports/grid-01-sendback-5b-report.md`.

### Remaining acceptance is not an ingress defect

The local-weight candidate removes the wholesale veto and is stable under the
requested resampler/dither comparisons. It still fails the exact Mau P labels,
the UDKM minimum/reference/timing criteria, and Lou's expressive timing pin.
The phase-coherent weak bass attacks at Mau P 188.928–189.865 s have 1–5 ms
peak offsets, so a phase-coherence-only correction does not reject them. The
stereo-max evidence and the 48 kHz DP frame geometry differ from the historical
mono/native path. No broadened classifier, arbitrary floor retuning or alternate
tracker clock from exploratory experiments is retained. Acceptance must be
resolved before the conditional one gated push and owner deployment/scan.

After the coherence correction, the memory bisect was repeated. Restoring each
of the same five implementations still leaves the final stereo results exactly
unchanged (657 / 969 / 200 flags). A stronger parity control patches only the
coherence function into unmodified `03d70f9`, feeds both implementations identical
canonical mono PCM, and uses float64 evidence to eliminate channel/precision
confounders. Both return exactly 653 / 982 / 201 flags, with **zero** changed
flags and **zero seconds** difference between every corresponding beat in all
three fixtures. Thus the retained memory refactors are equivalent after the fix,
not merely masked by the former section veto. The remaining stereo-max and
native-versus-canonical beat-path acceptance failures are explicit in the tests;
they were not concealed by rewriting expectations.

## Send-back 5c: nearest sufficient attack and reference acceptance

The attack picker now enumerates local peaks of the combined envelope within
±70 ms, keeps peaks at least 50% of that window's maximum, and selects the one
nearest the prediction. The same helper supplies evidence/phase for full grids,
rigid fitting, octave scoring and provisional-head beat candidates. Silence or
a monotone window without a peak supplies zero evidence. Strong-evidence,
hysteresis, local coherence, canonical ingress and memory rules are unchanged.

The 5b `grid-baseline-03d70f9.json` and `test_private_grid_keeps_shipped_timing`
were retired as directed. They were bisect instruments, not music references:
bit-exact ingress does not require 48 kHz expressive DP positions to reproduce
the old 44.1 kHz hop grid. The six-route resampler/dither robustness test remains.
Acceptance uses the owner's Mau P/UDKM CSVs, and Lou's attack support and local
inter-beat consistency; its old-grid F-measure is informational only.

The specified picker did not meet the exact musical acceptance. Mau P has
651 true positives and six false positives (two missed labelled bass drums), while
all 797 required timings remain within 10 ms. UDKM has 1,005 flags, 965 true
positives and 40 false positives (96.2013% agreement); its required reference
timings also fail. The explicit §2a stop condition was therefore applied: no
threshold tuning, section-boundary adjustment, full backend/frontend suite or push follows.
All disagreeing reference rows, including both channels' selected attack offsets
and energies, are in `/home/codex/src/reports/grid-01-sendback-5c-report.md`.

At the fixed Mau P reference time 149.552302448 s, the combined-envelope choice
moves from 0.140642 at +17.698 ms to 0.108287 at +7.698 ms. It is still labelled
on. At 188.927910152, 189.396667387 and 189.865424622 s, the fixed-prediction
nearest sufficient peak is already the largest peak, so this rule alone does
not remove those false flags. The report separates fixed-prediction effects
from final refitted grid times and lists every remaining mismatch.

Lou's stricter nearest-sufficient per-channel support is 184/197 flagged beats
(93.401%, passing 90%). With a nine-interval local median, two intervals exceed
+25%: 92.501333–93.472000 s (1.281690×) and 108.085333–109.109333 s
(1.333333×). Its tempo is 77.054795 BPM without doubling; informational F20ms
against the retired grid remains 0.930233. The self-consistency interval
criterion therefore also remains unaccepted, without restoring the old pin.

## Send-back 5d: owner verdicts and misplaced expressive beats

The owner listened to all disputed 5c spots on 2026-11-12; the verdict table
and current label authority are in `grid01-udkm-findings.md` and the reference
README. Mau P edits are data-only: rows 182/319 become full presence and
403/404/405/415/791/805 become reduced. The owner corrected the task's arithmetic
to 653 full, 155 absent and six reduced rows. Reduced rows are excluded from
binary scoring until BEAT-02 implements reduced intensity. No analyser
threshold is tuned to these reference changes.

UDKM's reference phase is now the first sufficient layered transient: fixed
129.985 BPM, median phase 0.373859195291779 s over 910 full-level body events
at 60–480 s, −16.840805 ms from the archived body phase. Presence ranges follow
the owner, not output flags. Body agreement at t ≥60 s is the gate; quiet intro
misses are reported with both channels' on/off-beat energy as the known gap
“soft bass drums in quiet intros”, the next BEAT-02 bench target.

The owner also corrected the initial Lou diagnosis: 1.28×/1.33× intervals are
misplaced beats, not missing beats. The proposed >1.5× insertion rule is retired;
it would not trigger and would create a short interval if forced. The approved
repair fits eight surrounding non-outlier beats, re-places the anomalous
passage and snaps to sufficient attacks. Count stays 215. At the two intervals,
0.970667 s becomes 0.820000 s and 1.024000 s becomes 0.795000 s. Only beat
indices 119, 120, 139 and 140 move. No intervals remain outside ±25% of the
nine-interval median, and 184/197 flagged beats (93.401015%) retain an attack
within ±20 ms. Mau P and UDKM final grids are unchanged. Synthetic regular and
expressive paths, including their silent passages, remain unchanged.

The 5c hard stop and historical failing scores above describe the earlier,
unverified references. They are not current acceptance failures. The 5d report
records the owner clarifications, corrected scores, retained memory/robustness
checks, the one gated push and its CI conclusions. Target validation starts on
LXC 115 “lampastream-bench”, with the service disabled before CLI analysis and
the single 192 kHz-inclusive library survey; LXC 112 deployment remains the
owner's later choice. No LMS/LAN or target deployment is performed here.
