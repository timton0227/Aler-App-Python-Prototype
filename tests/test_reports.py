"""Tests for alertmesh.reports.

Swift reference: ../alert-mesh/AlertMeshTests/AlertMesh/Protocols/CommunityReportPacketsTests.swift.
Test docstrings name the Swift test they port, where one exists.
"""
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from alertmesh import reports, wire
from alertmesh.reports import ReportKind, ReportSeverity


def test_constants_match_the_swift_app():
    assert reports.REPORT_ID_LENGTH == 16
    assert reports.SIGNING_KEY_LENGTH == 32
    assert reports.SIGNATURE_LENGTH == 64
    assert reports.NOTE_MAX_BYTES == 140
    assert reports.NICKNAME_MAX_BYTES == 32
    assert (reports.GEOHASH_MIN_LENGTH, reports.GEOHASH_MAX_LENGTH) == (2, 8)
    assert reports.SOS_GEOHASH_MAX_LENGTH == 7
    assert reports.HAZARD_MAX_LIFETIME_MS == 86_400_000
    assert reports.SOS_MAX_LIFETIME_MS == 21_600_000


def test_constants_wire_values_are_frozen():
    """Swift: wireValuesAreFrozen."""
    assert (ReportKind.HAZARD, ReportKind.SOS, ReportKind.SAFE) == (1, 2, 3)
    assert (ReportSeverity.LOW, ReportSeverity.MODERATE, ReportSeverity.HIGH) == (1, 2, 3)
    assert ReportSeverity.LOW < ReportSeverity.HIGH
    assert reports.MESSAGE_TYPE == 0x2E


def test_constants_signing_context_is_distinct():
    """Swift: signingContextIsFrozenAndDistinct (the constant part)."""
    assert reports.SIGNING_CONTEXT == "alertmesh-report-v1"
    assert reports.SIGNING_CONTEXT not in (wire.ALERT_SIGNING_CONTEXT, wire.CANCELLATION_SIGNING_CONTEXT)


def test_constants_report_severity_is_not_the_official_severity():
    assert ReportSeverity is not wire.Severity
    official_words = {s.name for s in wire.Severity}
    assert not official_words & {s.name for s in ReportSeverity}


SOS_FIELDS = dict(
    kind=ReportKind.SOS,
    report_id=bytes(range(16)),
    geohash="r7hg2bc",
    hazard_code=0,
    severity=None,
    note="Trapped on roof",
    author_signing_key=bytes(32),
    author_nickname="tim",
    created_at=1_700_000_000_000,
    expires_at=1_700_003_600_000,
)


def test_signing_bytes_start_with_context_then_kind():
    """Swift: signingContextIsFrozenAndDistinct. 0x13, "alertmesh-report-v1", then the kind."""
    hazard = reports.report_signing_bytes(**{**SOS_FIELDS, "kind": ReportKind.HAZARD})
    expected = bytes([0x13]) + b"alertmesh-report-v1" + bytes([0x01])
    assert hazard[: len(expected)] == expected


def test_signing_bytes_differ_by_kind_so_sos_cannot_become_safe():
    sos = reports.report_signing_bytes(**SOS_FIELDS)
    safe = reports.report_signing_bytes(**{**SOS_FIELDS, "kind": ReportKind.SAFE})
    assert sos != safe
    assert sos[20] == 0x02 and safe[20] == 0x03


def test_signing_bytes_layout_matches_the_spec():
    sb = reports.report_signing_bytes(**SOS_FIELDS)
    off = 21
    assert sb[off : off + 16] == bytes(range(16)); off += 16
    assert sb[off : off + 9] == b"\x00\x07r7hg2bc"; off += 9
    assert sb[off : off + 2] == b"\x00\x00"; off += 2  # no hazard, no severity
    assert sb[off : off + 17] == b"\x00\x0fTrapped on roof"; off += 17
    assert sb[off : off + 32] == bytes(32); off += 32
    assert sb[off : off + 5] == b"\x00\x03tim"; off += 5
    assert sb[off:] == (1_700_000_000_000).to_bytes(8, "big") + (1_700_003_600_000).to_bytes(8, "big")


def test_signing_bytes_severity_and_hazard_are_signed():
    base = {**SOS_FIELDS, "kind": ReportKind.HAZARD, "hazard_code": 1}
    low = reports.report_signing_bytes(**{**base, "severity": ReportSeverity.LOW})
    high = reports.report_signing_bytes(**{**base, "severity": ReportSeverity.HIGH})
    other_hazard = reports.report_signing_bytes(**{**base, "severity": ReportSeverity.LOW, "hazard_code": 2})
    assert low != high
    assert low != other_hazard


def test_signing_bytes_of_a_report_match_the_function():
    report = reports.CommunityReport(**SOS_FIELDS, signature=bytes(64))
    assert reports.signing_bytes_of(report) == reports.report_signing_bytes(**SOS_FIELDS)
    assert report.hazard is None


# --- Encode, decode, validation (step 3.3). Signatures are dummies here: decoding
# checks structure only. Signing and verifying are step 3.4.

HOUR = 60 * 60 * 1000


def unsigned(kind=ReportKind.HAZARD, geohash="r7hg2bc", hazard_code=1, severity=ReportSeverity.MODERATE,
             note="Causeway under water, cars turning back", nickname="tim", created_at=1_700_000_000_000,
             lifetime_ms=2 * HOUR, key=bytes(32)):
    return reports.CommunityReport(kind, bytes(range(16)), geohash, hazard_code, severity, note, key,
                                   nickname, created_at, created_at + lifetime_ms, bytes(64))


def unsigned_sos(**kw):
    kw.setdefault("lifetime_ms", HOUR)
    return unsigned(kind=ReportKind.SOS, hazard_code=0, severity=None, note="Trapped on roof", **kw)


def round_trips(report):
    return reports.decode(reports.encode(report)) == report


def value_offset(tlv_type, data):
    off = 0
    while off + 3 <= len(data):
        t, length = data[off], (data[off + 1] << 8) | data[off + 2]
        if off + 3 + length > len(data):
            return None
        if t == tlv_type:
            return off + 3
        off += 3 + length
    return None


# Swift: frozenSOSHex. Everything before the signature; signed by the key whose seed is 0x01..0x20.
FROZEN_SOS_PREFIX_HEX = (
    "01000102020010000102030405060708090a0b0c0d0e0f0300077237686732626306"
    "000f54726170706564206f6e20726f6f6607002079b5562e8fe654f94078b112e8a9"
    "8ba7901f853ae695bed7e0e3910bad04966408000374696d0900080000018bcfe568"
    "000a00080000018bd01c56800b0040"
)
FROZEN_SEED = bytes(range(1, 33))


def test_encode_frozen_sos_prefix():
    """Swift: frozenSOSEncodesToTheFrozenBytes (structure part)."""
    key = Ed25519PrivateKey.from_private_bytes(FROZEN_SEED).public_key().public_bytes_raw()
    sos = reports.CommunityReport(ReportKind.SOS, bytes(range(16)), "r7hg2bc", 0, None, "Trapped on roof",
                                  key, "tim", 1_700_000_000_000, 1_700_003_600_000, bytes(64))
    prefix = bytes.fromhex(FROZEN_SOS_PREFIX_HEX)
    encoded = reports.encode(sos)
    assert encoded[: len(prefix)] == prefix
    assert len(encoded) == len(prefix) + 64


def test_encode_prefix_is_frozen():
    """Swift: encodedPrefixIsFrozen. kind TLV (sos), then the reportID TLV header."""
    assert reports.encode(unsigned_sos())[:7] == bytes([0x01, 0x00, 0x01, 0x02, 0x02, 0x00, 0x10])


def test_encode_round_trips_for_every_kind():
    """Swift: hazardReportRoundTrip, sosRoundTripCarriesNoHazardOrSeverity, safeCheckInRoundTrip,
    emptyNoteAndNicknameAreAllowed (structure parts)."""
    assert round_trips(unsigned(hazard_code=2, severity=ReportSeverity.HIGH))
    sos = reports.decode(reports.encode(unsigned_sos()))
    assert sos.hazard is None and sos.hazard_code == 0 and sos.severity is None
    assert round_trips(unsigned(kind=ReportKind.SAFE, hazard_code=0, severity=None, note="", lifetime_ms=HOUR))
    assert round_trips(unsigned(note="", nickname=""))


def test_encode_omits_absent_hazard_and_severity_fields():
    encoded = reports.encode(unsigned_sos())
    assert value_offset(0x04, encoded) is None
    assert value_offset(0x05, encoded) is None


def test_validation_sos_and_safe_are_capped_at_precision_seven():
    """Swift: sosRejectsGeohashFinerThanPrecisionSeven, safeRejectsGeohashFinerThanPrecisionSeven,
    sosAcceptsPrecisionSevenAndCoarser, hazardReportAcceptsPrecisionEight."""
    assert reports.decode(reports.encode(unsigned_sos(geohash="r7hg2bcd"))) is None
    safe = unsigned(kind=ReportKind.SAFE, geohash="r7hg2bcd", hazard_code=0, severity=None, lifetime_ms=60_000)
    assert reports.decode(reports.encode(safe)) is None
    for cell in ("r7hg2bc", "r7hg", "r7"):
        assert round_trips(unsigned_sos(geohash=cell)), cell
    assert round_trips(unsigned(geohash="r7hg2bcd"))


def test_validation_lifetimes():
    """Swift: rejectsExpiryBeforeCreation, hazardRejectsLifetimeBeyondADay, sosRejectsLifetimeBeyondSixHours."""
    r = unsigned()
    backwards = reports.CommunityReport(r.kind, r.report_id, r.geohash, r.hazard_code, r.severity, r.note,
                                        r.author_signing_key, r.author_nickname, r.expires_at, r.created_at, r.signature)
    assert reports.decode(reports.encode(backwards)) is None
    assert reports.decode(reports.encode(unsigned(lifetime_ms=reports.HAZARD_MAX_LIFETIME_MS + 1))) is None
    assert round_trips(unsigned(lifetime_ms=reports.HAZARD_MAX_LIFETIME_MS))
    assert reports.decode(reports.encode(unsigned_sos(lifetime_ms=reports.SOS_MAX_LIFETIME_MS + 1))) is None
    assert round_trips(unsigned_sos(lifetime_ms=reports.SOS_MAX_LIFETIME_MS))


def test_validation_field_bounds():
    """Swift: hazardReportRequiresSeverity, rejectsOversizedNote, rejectsOversizedNickname,
    rejectsInvalidGeohashCharacters, rejectsGeohashOutsidePrecisionBounds, rejectsWrongLengthAuthorKey."""
    bad = [
        unsigned(severity=None),
        unsigned(note="n" * (reports.NOTE_MAX_BYTES + 1)),
        unsigned(nickname="n" * (reports.NICKNAME_MAX_BYTES + 1)),
        unsigned(geohash="ails"),
        unsigned(geohash="r"),
        unsigned(geohash=""),
        unsigned(geohash="r7hg2bcd9"),
        unsigned(key=bytes([0xAB]) * 31),
    ]
    for report in bad:
        assert reports.decode(reports.encode(report)) is None
    assert round_trips(unsigned(note="n" * reports.NOTE_MAX_BYTES, nickname="k" * reports.NICKNAME_MAX_BYTES))


def test_validation_unknown_severity_and_kind_are_rejected():
    """Swift: rejectsUnknownSeverity, rejectsUnknownKind."""
    encoded = bytearray(reports.encode(unsigned()))
    encoded[value_offset(0x05, encoded)] = 0x7F
    assert reports.decode(bytes(encoded)) is None
    encoded = bytearray(reports.encode(unsigned()))
    encoded[value_offset(0x01, encoded)] = 0x7F
    assert reports.decode(bytes(encoded)) is None
    assert reports.kind_peek(bytes(encoded)) is None


def test_validation_unknown_hazard_is_kept():
    decoded = reports.decode(reports.encode(unsigned(hazard_code=0x7F, severity=ReportSeverity.LOW)))
    assert decoded.hazard is None and decoded.hazard_code == 0x7F


def test_validation_duplicates_rejected_unknown_tlvs_skipped():
    """Swift: rejectsDuplicateKindTLV, rejectsDuplicateGeohashTLV, toleratesUnknownTLVs,
    rejectsTruncatedPayload, rejectsMissingSignature."""
    encoded = reports.encode(unsigned_sos())
    assert reports.decode(encoded + bytes([0x01, 0x00, 0x01, 0x03])) is None
    assert reports.decode(encoded + bytes([0x03, 0x00, 0x02, 0x72, 0x37])) is None
    assert reports.decode(encoded + bytes([0x7F, 0x00, 0x02, 0xDE, 0xAD])) == unsigned_sos()
    assert reports.decode(encoded[:-1]) is None
    assert reports.decode(encoded[: -3 - reports.SIGNATURE_LENGTH]) is None


def test_validation_kind_peek():
    """Swift: kindPeekMatchesDecodedKind, kindPeekReturnsNilOnGarbage."""
    for kind in ReportKind:
        is_hazard = kind == ReportKind.HAZARD
        r = unsigned(kind=kind, hazard_code=1 if is_hazard else 0,
                     severity=ReportSeverity.LOW if is_hazard else None, lifetime_ms=60_000)
        encoded = reports.encode(r)
        assert reports.kind_peek(encoded) is kind
        assert reports.decode(encoded).kind is kind
    assert reports.kind_peek(bytes([0x00, 0x01, 0x02])) is None
    assert reports.kind_peek(b"") is None


def test_validation_a_report_is_not_an_official_alert():
    """Swift: aReportIsNotAnOfficialAlert."""
    assert wire.decode(reports.encode(unsigned())) is None
