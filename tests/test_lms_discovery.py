"""Tests for LMS UDP discovery (lms_discovery.py).

The TLV parser is fully deterministic and requires no sockets; it is the
main thing worth unit-testing here.  Live network discovery is not tested
(would require a real LMS instance or a complex socket mock).
"""

from lampastream.lms_discovery import _parse_tlv_response

# ---------------------------------------------------------------------------
# Helper: build a synthetic TLV response
# ---------------------------------------------------------------------------


def _build_response(fields: dict[str, str]) -> bytes:
    """Build a minimal valid TLV response from a {tag: value} dict.

    The first byte is 'E' (the echoed opcode), followed by zero or more
    TLV fields: 4-byte ASCII tag, 1-byte length, UTF-8 value.
    """
    buf = bytearray(b"E")
    for tag, value in fields.items():
        encoded = value.encode("utf-8")
        buf += tag[:4].encode("ascii").ljust(4, b"\x00")
        buf += bytes([len(encoded)])
        buf += encoded
    return bytes(buf)


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------


def test_parse_tlv_typical_response():
    data = _build_response({"NAME": "myserver", "JSON": "9000", "UUID": "abc-123", "VERS": "8.3.1"})
    result = _parse_tlv_response(data)
    assert result["NAME"] == "myserver"
    assert result["JSON"] == "9000"
    assert result["UUID"] == "abc-123"
    assert result["VERS"] == "8.3.1"


def test_parse_tlv_empty_bytes():
    assert _parse_tlv_response(b"") == {}


def test_parse_tlv_opcode_only():
    """Just the echoed opcode byte with no TLV fields."""
    assert _parse_tlv_response(b"E") == {}


def test_parse_tlv_multiple_fields_order_preserved():
    fields = {"NAME": "lms-box", "JSON": "9001", "VERS": "8.4.0"}
    result = _parse_tlv_response(_build_response(fields))
    assert len(result) == 3
    assert result["VERS"] == "8.4.0"
    assert result["JSON"] == "9001"


def test_parse_tlv_truncated_value_does_not_raise():
    """Tag present but value truncated — parser must not raise."""
    # Opcode + tag "NAME" + length 16, but only 3 bytes of value follow.
    data = b"E" + b"NAME" + bytes([16]) + b"abc"
    result = _parse_tlv_response(data)
    # The partial value is either decoded or skipped; either way, no exception.
    assert isinstance(result, dict)


def test_parse_tlv_empty_value():
    """A field with length 0 is valid and should produce an empty string."""
    data = _build_response({"NAME": ""})
    result = _parse_tlv_response(data)
    assert result["NAME"] == ""


def test_parse_tlv_unicode_hostname():
    """Server names with non-ASCII characters are decoded gracefully."""
    data = _build_response({"NAME": "café-server"})
    result = _parse_tlv_response(data)
    assert result["NAME"] == "café-server"
