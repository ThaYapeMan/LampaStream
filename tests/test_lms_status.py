"""Tests for lms_status._parse_status and _parse_sync_response.

query_lms_status() and query_lms_sync_peers() open real TCP sockets, so they
are not tested here.  The parser functions operate on plain strings and are
fully testable in isolation.

LMS CLI responses are fully URL-encoded, including the colon between key and
value (%3A).  _build_response() produces that wire format so tests exercise
the same encoding the production parser sees.
"""

from urllib.parse import quote

import pytest
from pytest import approx

from lampastream.lms_status import (
    LmsPlayerStatus,
    _parse_status,
    _parse_sync_response,
    query_lms_status,
    query_lms_sync_peers,
)


def _build_response(*fields: str) -> str:
    """Build a minimal LMS status response in the actual wire format.

    Each field is a decoded 'key:value' string; it is URL-encoded here
    exactly as LMS would encode it before sending.
    """
    encoded = [quote(f, safe="") for f in fields]
    return "aa%3Abb%3Acc%3Add%3Aee%3Aff status 0 1 " + " ".join(encoded)


# ---------------------------------------------------------------------------
# Basic field parsing
# ---------------------------------------------------------------------------

def test_parse_time():
    result = _parse_status(_build_response("time:102.647383"))
    assert result.time == approx(102.647383)


def test_parse_sync_master():
    result = _parse_status(_build_response("time:30.0", "sync_master:11:22:33:44:55:66"))
    assert result.sync_master == "11:22:33:44:55:66"


def test_parse_sync_master_empty_means_none():
    """LMS sends sync_master: with an empty value when the player is standalone."""
    result = _parse_status(_build_response("time:10.0", "sync_master:"))
    assert result.sync_master is None


def test_parse_sync_slaves_single():
    result = _parse_status(_build_response("sync_slaves:aa:bb:cc:00:11:22"))
    assert result.sync_slaves == ["aa:bb:cc:00:11:22"]


def test_parse_sync_slaves_multiple():
    result = _parse_status(_build_response("sync_slaves:aa:bb:cc:00:11:22,dd:ee:ff:00:11:22"))
    assert result.sync_slaves == ["aa:bb:cc:00:11:22", "dd:ee:ff:00:11:22"]


def test_parse_sync_slaves_empty():
    result = _parse_status(_build_response("sync_slaves:"))
    assert result.sync_slaves == []


def test_parse_standalone_player():
    """A standalone player has no sync_master or sync_slaves tokens at all."""
    result = _parse_status(_build_response("time:55.1", "player_name:LampaStream"))
    assert result.time == approx(55.1)
    assert result.player_name == "LampaStream"
    assert result.sync_master is None
    assert result.sync_slaves == []


def test_parse_player_name_with_space():
    """Player names with spaces are encoded as %20 in the value."""
    result = _parse_status(_build_response("player_name:Study Room"))
    assert result.player_name == "Study Room"


def test_parse_player_name_with_internal_colons():
    """Player names like 'Study (Sonos)' that were formerly 'SONOS::Study' encode
    the colons as %3A in the value; partition(%3A) must split on the FIRST one."""
    result = _parse_status(_build_response("player_name:SONOS::Study"))
    assert result.player_name == "SONOS::Study"


def test_parse_mac_in_player_id_not_confused_with_fields():
    """The encoded player MAC at the start of the response must not be parsed as a field.

    partition('%3A') on 'aa%3Abb...' yields key_raw='aa', which is not a
    recognised field name and is skipped.
    """
    text = "aa%3Abb%3Acc%3Add%3Aee%3Aff status 0 1 time%3A1.0"
    result = _parse_status(text)
    assert result.time == approx(1.0)
    assert result.sync_master is None


def test_parse_defaults_when_empty():
    assert _parse_status("") == LmsPlayerStatus()


# ---------------------------------------------------------------------------
# Robustness: tricky token shapes
# ---------------------------------------------------------------------------

def test_parse_mac_value_and_space_in_key():
    """Two edge cases in one response:

    - sync_master value is a MAC with multiple encoded colons; only the first
      %3A (the structural separator) must be used to split key from value.
    - mixer%20volume is a real LMS field whose name contains a space after
      decoding; the parser must not crash or corrupt other fields.
    """
    text = (
        "aa%3Abb%3Acc%3Add%3Aee%3Aff status 0 1 "
        "sync_master%3A94%3A9f%3A3e%3Afa%3Aba%3A66 "
        "mixer%20volume%3A82"
    )
    result = _parse_status(text)
    assert result.sync_master == "94:9f:3e:fa:ba:66"
    # "mixer volume" is not a recognised field; it must be silently ignored.
    assert result.player_name is None


def test_parse_lowercase_encoded_separator():
    """%3a (lowercase) is valid URL-encoding and must be treated as %3A."""
    text = "player_name%3aLampaStream sync_master%3a94%3a9f%3a3e%3afa%3aba%3a66"
    result = _parse_status(text)
    assert result.player_name == "LampaStream"
    assert result.sync_master == "94:9f:3e:fa:ba:66"


# ---------------------------------------------------------------------------
# Regression: exact production response that exposed the %3A parser bug
# ---------------------------------------------------------------------------

def test_parse_fully_encoded_response():
    """Regression: LMS response from production where all three key fields
    are present and the separator is %3A throughout."""
    text = (
        "02%3Aae%3A8a%3Ab0%3A24%3A9b status 0 1 "
        "player_name%3ALampaStream "
        "sync_master%3A94%3A9f%3A3e%3Afa%3Aba%3A66 "
        "sync_slaves%3A02%3Aae%3A8a%3Ab0%3A24%3A9b"
    )
    result = _parse_status(text)
    assert result.player_name == "LampaStream"
    assert result.sync_master == "94:9f:3e:fa:ba:66"
    assert result.sync_slaves == ["02:ae:8a:b0:24:9b"]


def test_parse_status_no_sync_master_when_stopped():
    """LMS omits sync_master from the status response when the player is stopped.

    This is the regression scenario: player_name parses correctly (confirming
    the right player is found) but sync_master is absent — LMS only includes
    it during active playback.  The poller falls back to 'sync ?' in this case.
    """
    text = (
        "02%3Aae%3A8a%3Ab0%3A24%3A9b status 0 1 "
        "player_name%3ALampaStream "
        "time%3A0.0"
        # No sync_master or sync_slaves — player is stopped
    )
    result = _parse_status(text)
    assert result.player_name == "LampaStream"
    assert result.sync_master is None
    assert result.sync_slaves == []


# ---------------------------------------------------------------------------
# _parse_sync_response — the 'sync ?' fallback
# ---------------------------------------------------------------------------


def test_parse_sync_response_standalone():
    """'-' means the player has no sync peers."""
    assert _parse_sync_response("aa%3Abb%3Acc%3Add%3Aee%3Aff sync -") == []


def test_parse_sync_response_single_peer():
    """Single sync peer: Sonos MAC returned as the only peer."""
    result = _parse_sync_response(
        "02%3Aae%3A8a%3Ab0%3A24%3A9b sync 94%3A9f%3A3e%3Afa%3Aba%3A66"
    )
    assert result == ["94:9f:3e:fa:ba:66"]


def test_parse_sync_response_multiple_peers():
    """Multiple sync peers: commas are URL-encoded as %2C."""
    result = _parse_sync_response(
        "02%3Aae%3A8a%3Ab0%3A24%3A9b sync "
        "94%3A9f%3A3e%3Afa%3Aba%3A66%2Ccc%3Add%3Aee%3Aff%3A00%3A11"
    )
    assert result == ["94:9f:3e:fa:ba:66", "cc:dd:ee:ff:00:11"]


def test_parse_sync_response_empty():
    """Empty or truncated response returns an empty list."""
    assert _parse_sync_response("") == []
    assert _parse_sync_response("02%3Aae sync") == []  # missing peers token


def test_parse_sync_response_matches_production_mac():
    """Regression: the Sonos MAC 94:9f:3e:fa:ba:66 survives the decode round-trip."""
    peers = _parse_sync_response(
        "02%3Aae%3A8a%3Ab0%3A24%3A9b sync 94%3A9f%3A3e%3Afa%3Aba%3A66"
    )
    assert peers == ["94:9f:3e:fa:ba:66"]


# ---------------------------------------------------------------------------
# Host validation — empty lms_host must never silently become a DNS lookup
# ---------------------------------------------------------------------------


def test_query_lms_status_raises_on_empty_host():
    """query_lms_status must raise ValueError for an empty host before opening
    any socket.  Empty string passed to getaddrinfo on Linux produces
    [Errno -2] Name or service not known — an opaque OS error with no hint
    that the profile is misconfigured.  A ValueError surfaces the real cause.
    """
    with pytest.raises(ValueError, match="LMS host is not configured"):
        query_lms_status("", "aa:bb:cc:dd:ee:ff")


def test_query_lms_sync_peers_raises_on_empty_host():
    """Same contract for query_lms_sync_peers."""
    with pytest.raises(ValueError, match="LMS host is not configured"):
        query_lms_sync_peers("", "aa:bb:cc:dd:ee:ff")
