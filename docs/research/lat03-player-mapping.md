# LAT-03: continuous LMS room mapping

Evidence: owner archive `ab-20261101-1520.tar.gz`, its reference analysis kit,
`lat-journal.txt`, and baseline `82181c5`. The archive reports that same deployed
commit. Journal display times are CET, one hour ahead of the manifest's UTC.
These are software/position measurements, not acoustic measurements at Sonos.

## What moved

The journal records one own-player seek, at 15:07:08.046 CET, to 6.392 s.
It records no later alignment or clock discontinuity during this run. The CLI
packet trace confirms the single seek and `playerpref playDelay 0`. Repeated
seeking therefore did **not** cause this particular step.

The startup applied delay was 112 ms. Accepted own-minus-followed position
residuals start at −71.246 ms (15:07:13), pass −4.026 ms (15:09:14), and end
at +129.778 ms (15:13:16): about 0.55–0.7 ms/s drift. Interspersed residuals
around −725 and +275 ms were rejected. The code required the untrimmed estimate
including playDelay to be nonnegative. Negative estimates could establish
consensus but never update the saved/applied delay or clear `first`.

Replaying the baseline estimator with the observed 112 ms startup delay,
zero playDelay and zero trim gives its first change at 15:09:44.737:
**112 → 13 ms**, an instantaneous −99 ms change because `first` was still true.
Subsequent targets are 27, 37, 48, 63, 69, 74, 87, 97, 113, 121 and 131 ms.
The archive did not export the saved configuration or every applied-delay value;
this reconstruction is consistent with, rather than a direct recording of, that
configuration. New mapping logs record applied and target values explicitly.

Using each detection's wall time, the latest reconstructed applied delay, and
interpolation between the non-excursion position pairs gives the decomposition
below. Here `offset ≈ applied − position_residual + remainder`. Medians of
individual terms need not sum exactly to the median of their sum.

| Track bin (s) | Observed offset (ms) | Applied (ms) | Own − followed (ms) | Remainder (ms) |
|---|---:|---:|---:|---:|
| 0–30 | +212.22 | 112 | −66.61 | +34.24 |
| 30–60 | +205.72 | 112 | −51.10 | +41.46 |
| 60–90 | +180.82 | 112 | −37.25 | +30.60 |
| 90–120 | +182.38 | 112 | −21.86 | +48.29 |
| 120–150 | +157.21 | 112 | −2.54 | +43.49 |
| 150–180 | +41.67 | 27 | +18.51 | +33.48 |
| 180–210 | +36.38 | 37 | +38.45 | +41.74 |
| 210–240 | +35.36 | 48 | +53.38 | +41.95 |

Thus the roughly 170 ms start-to-settled change comprises roughly 70 ms of
position drift plus the 99 ms applied-delay jump. No timing-tail/SHM anchor
telemetry was captured, so it is not possible to separate native clock error,
subscription anchor error, detector phase and real speaker output latency inside
the remaining approximately 40 ms. A fixed Sonos correction is not justified by
this archive. In particular, the supplied reference CSV starts at **0.476 s**,
not the task's **0.499 s**; its median difference from that rigid 128 BPM grid is
−11.35 ms (MAD 3.45 ms), not a uniform −23 ms. Neither discrepancy is proof of
a Sonos pipeline offset. The supplied `claude/ab-capture-analysis-2026-11-01.md`
write-up was not present in this checkout/share; the archive and kit were read
directly.

## Player-layer correction

`latency.py` restores the room's saved signed estimate plus trim at construction.
Signed estimates matter: an independently aligned virtual player can lag the
room. Four consistent samples still establish a plausible target; excursions,
changed-track pairs, nonfinite and ≥5 s mismatches remain rejected. Both initial
consensus and later refinement use an elapsed-time limit of **5 ms/s**, with no
first-estimate jump and no accumulated idle-time credit for a newly chosen
target. Getter and sampler updates share a short lock. Persistence saves the
consensus estimate, not the partly applied correction.

`LmsAudibleClock` preserves signed offsets for the native player clock. Causal
receipt-time fallback still has no negative lookahead. Smooth probe changes do
not change the clock generation and retire queued work. Other probes keep their
existing generation behavior; AirPlay's mapping is unchanged.

The follower marks startup alignment as consumed for the track and aligns each
new mirrored track once after decoder readiness. The probe no longer initiates
late seeks when positions disagree. Explicit user seeks still relay to the
virtual player. Large mismatches are diagnostic/rejected rather than repeated
mid-track playback commands.

`LmsTrackPositionSource` also slews small subscription-anchor corrections at
5 ms/s. Track/transport changes and large seeks establish a new anchor. This
bounds logger/preview corrections separately from the physical audible clock.
No analyser, renderer, scheduler or hardware output code changed.

## What the local tests do and do not prove

`test_lat03_mapping.py` exercises a 200 ms position error, positive and negative
remembered offsets, small subscription corrections, intentional seeks, and real
locked 128 BPM BeatDetector publications through both clock mappings. Correct
remembered sessions stay within 15 ms from their first sample; a wrong estimate
converges continuously. Correctness from the first locked beat cannot be promised
for an unknown or wrong saved estimate: a 200 ms correction at 5 ms/s needs at
least 40 seconds after consensus. A remembered relative position estimate can
also become stale when startup alignment changes. These are explicit field risks,
not evidence that the requested first-bin acceptance has passed.

Owner acceptance remains a fresh same-track capture: LMS offsets within ±40 ms
starting in the first bin, adjacent medians changing by less than 20 ms, and
AirPlay unchanged. An acoustic reference and native-clock telemetry are needed
before assigning the unexplained remainder to a fixed Sonos output offset.
