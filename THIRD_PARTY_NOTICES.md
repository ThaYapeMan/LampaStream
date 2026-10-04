# LampaStream distribution notices

LampaStream's own code is MIT licensed. The separately built yeney-player is
PolyForm Noncommercial 1.0.0, from ThaYapeMan/yeney-core at
45779a4383929840a46a931fc1519b4778b64a72. This does not change either licence.

Complete distribution texts:

- [yeney-core LICENSE](distribution/yeney-core/LICENSE)
- [yeney-core THIRD_PARTY_NOTICES](distribution/yeney-core/THIRD_PARTY_NOTICES.md):
  libFLAC BSD-3-Clause, minimp3 CC0 1.0 and Apple ALAC Apache-2.0.

These exact upstream copies are included in LampaStream wheels and installed
alongside yeney-player by the repository installer.

Music colour support uses Pillow for median-cut image quantisation (MIT-CMU in
current releases; historical releases use the permissive HPND licence) and HTTPX
for artwork requests (BSD-3-Clause). They are installed as separate dependencies
with their own distribution licence texts. OKLab's published mathematics are
credited to Björn Ottosson: https://bottosson.github.io/posts/oklab/ (public
domain/MIT). No LedFx or aubio source or package is included or required by this
feature.
