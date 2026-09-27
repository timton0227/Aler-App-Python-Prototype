"""What one phone keeps: the newest verified version of each person's reports.

Ported from: ../alert-mesh/AlertMesh/AlertMesh/Services/CommunityReportStore.swift

A record is one (author key, report ID) pair. A later version from the SAME author
replaces it; that is how "I'm safe" answers an SOS. A stranger reusing the ID makes a
separate record, so nobody can mark someone else safe.

Each author gets two separate quotas: 5 hazard reports and 2 check-ins (SOS or
"safe"). With one shared counter, a person's own fifth hazard report would push out
their SOS.

This is free and unencumbered software released into the public domain.
"""
from alertmesh import reports
from alertmesh.alert_store import CLOCK_SKEW_MS, IngestResult, _system_clock_ms
from alertmesh.reports import CommunityReport, ReportKind, ReportSeverity

MAX_REPORTS = 300
MAX_HAZARD_REPORTS_PER_AUTHOR = 5
MAX_CHECK_INS_PER_AUTHOR = 2

# Shown first: SOS, then hazards, then "safe".
_DISPLAY_RANK = {ReportKind.SOS: 0, ReportKind.HAZARD: 1, ReportKind.SAFE: 2}
# Dropped first when full: hazards, then "safe", and an SOS last of all.
_EVICTION_RANK = {ReportKind.HAZARD: 0, ReportKind.SAFE: 1, ReportKind.SOS: 2}


def _is_check_in(kind: ReportKind) -> bool:
    return kind != ReportKind.HAZARD


def _max_lifetime_ms(kind: ReportKind) -> int:
    return reports.HAZARD_MAX_LIFETIME_MS if kind == ReportKind.HAZARD else reports.SOS_MAX_LIFETIME_MS


def _key(report: CommunityReport) -> bytes:
    return report.author_signing_key + report.report_id


class ReportStore:
    """One phone's community reports. `clock` returns "now" in milliseconds."""

    def __init__(self, clock=_system_clock_ms):
        self.clock = clock
        self._reports: dict[bytes, tuple[CommunityReport, bytes]] = {}  # key -> (report, payload), oldest first

    # --- Ingest ---

    def ingest(self, report: CommunityReport) -> IngestResult:
        """Take a decoded report. Checks the author's signature first."""
        if not reports.verify(report):
            return IngestResult.REJECTED
        now = self.clock()
        self._prune(now)
        if report.expires_at <= now:
            return IngestResult.REJECTED
        if report.created_at > now + CLOCK_SKEW_MS or report.expires_at > now + _max_lifetime_ms(report.kind) + CLOCK_SKEW_MS:
            return IngestResult.REJECTED

        key = _key(report)
        held = self._reports.get(key)
        if held is not None:
            if report.created_at == held[0].created_at:
                return IngestResult.DUPLICATE
            # A stale SOS arriving after the "safe" must not bring the call back.
            if not reports.supersedes(report, held[0]):
                return IngestResult.REJECTED
            del self._reports[key]
        self._reports[key] = (report, reports.encode(report))

        author = report.author_signing_key
        check_in = _is_check_in(report.kind)
        bucket = [k for k, (r, _) in self._reports.items()
                  if r.author_signing_key == author and _is_check_in(r.kind) == check_in]
        self._evict(bucket, MAX_CHECK_INS_PER_AUTHOR if check_in else MAX_HAZARD_REPORTS_PER_AUTHOR)
        self._evict(list(self._reports), MAX_REPORTS)
        return IngestResult.ACCEPTED

    def ingest_payload(self, payload: bytes) -> IngestResult:
        report = reports.decode(payload)
        return IngestResult.REJECTED if report is None else self.ingest(report)

    # --- Reads ---

    def live_reports(self) -> list[CommunityReport]:
        """SOS first, then hazards (most serious first), then "safe"; newest first within each."""
        self._prune(self.clock())

        def order(r: CommunityReport):
            severity = int(r.severity or ReportSeverity.LOW) if r.kind == ReportKind.HAZARD else 0
            return (_DISPLAY_RANK[r.kind], -severity, -r.created_at)

        return sorted((r for r, _ in self._reports.values()), key=order)

    def sync_candidates(self) -> list[bytes]:
        self._prune(self.clock())
        return [payload for _, payload in self._reports.values()]

    def wipe(self) -> None:
        self._reports.clear()

    # --- Internals ---

    def _evict(self, candidates: list[bytes], keep: int) -> None:
        excess = len(candidates) - keep
        if excess <= 0:
            return
        ranked = sorted(candidates, key=lambda k: (_EVICTION_RANK[self._reports[k][0].kind], self._reports[k][0].created_at))
        for k in ranked[:excess]:
            del self._reports[k]

    def _prune(self, now: int) -> None:
        self._reports = {k: v for k, v in self._reports.items() if v[0].expires_at > now}
