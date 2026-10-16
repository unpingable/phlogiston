"""Deterministic, synthetic-only static SCV0 demo export."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from html import escape
from pathlib import Path, PurePosixPath
from typing import Final, Mapping

from community_space_artifact import (
    ArtifactReceiptReferences,
    BoundedSourcePresentation,
    DisclosureMode,
    DisclosurePolicy,
    ProjectionArtifact,
    ProjectionArtifactEntry,
)
from community_space_comprehension import (
    ComprehensionVerdict,
    SyntheticComprehensionInstrument,
)
from community_space_feed import (
    FeedPublicationRequest,
    LocalProjectionFeedBoundary,
    PublicProjectionChannel,
)
from community_space_prototype import LocalCommunityPrototype, PrototypeSite

DEMO_VERSION: Final = "scv0-static-public-demo/1"

_STATES: Final = (
    "added",
    "changed_at_source",
    "source_unavailable",
    "removed",
)

_STATE_TITLES: Final = {
    "added": "Added",
    "changed_at_source": "Changed at source",
    "source_unavailable": "Source unavailable",
    "removed": "Removed",
}

_CLAIMS: Final = (
    "synthetic_fixture_only",
    "exact_canonical_m6b_pages_embedded",
    "exact_m6a_feed_bytes_embedded",
    "m6c_synthetic_information_sufficient",
    "file_digests_recorded",
)

_NON_CLAIMS: Final = (
    "live_atproto_data",
    "human_comprehension",
    "human_usability",
    "reader_authentication",
    "reader_authorization",
    "membership",
    "moderator_authority",
    "governance_authority",
    "source_truth",
    "source_ownership",
    "repository_currentness",
    "production_readiness",
)

_SHA_RE: Final = re.compile(r"sha256:[0-9a-f]{64}")


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _safe_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValueError("demo file path must be a non-empty POSIX path")
    parsed = PurePosixPath(value)
    if (
        parsed.is_absolute()
        or str(parsed) != value
        or any(part in {"", ".", ".."} for part in parsed.parts)
    ):
        raise ValueError("demo file path must be relative and normalized")
    return value


@dataclass(frozen=True, slots=True)
class DemoFile:
    path: str
    media_type: str
    body: bytes
    body_sha256: str

    def __post_init__(self) -> None:
        _safe_path(self.path)
        if not isinstance(self.media_type, str) or not self.media_type:
            raise ValueError("demo media type must be non-empty")
        if not isinstance(self.body, bytes):
            raise TypeError("demo file body must be bytes")
        if _SHA_RE.fullmatch(self.body_sha256) is None:
            raise ValueError("demo file digest must be a sha256 identifier")
        if _digest(self.body) != self.body_sha256:
            raise ValueError("demo file digest does not match body")

    @classmethod
    def create(cls, path: str, media_type: str, body: bytes) -> DemoFile:
        return cls(
            path=path,
            media_type=media_type,
            body=body,
            body_sha256=_digest(body),
        )

    def to_manifest_entry(self) -> dict[str, object]:
        return {
            "path": self.path,
            "mediaType": self.media_type,
            "bytes": len(self.body),
            "sha256": self.body_sha256,
        }


@dataclass(frozen=True, slots=True)
class StaticDemoBundle:
    files: tuple[DemoFile, ...]
    scenarios: tuple[dict[str, str], ...]
    verified_claims: tuple[str, ...] = _CLAIMS
    explicit_non_claims: tuple[str, ...] = _NON_CLAIMS
    demo_version: str = DEMO_VERSION

    def __post_init__(self) -> None:
        if self.demo_version != DEMO_VERSION:
            raise ValueError("unsupported static demo version")
        if self.verified_claims != _CLAIMS or self.explicit_non_claims != _NON_CLAIMS:
            raise ValueError("static demo claims and non-claims are fixed")
        if not isinstance(self.files, tuple) or not self.files:
            raise ValueError("static demo requires files")
        if len({item.path for item in self.files}) != len(self.files):
            raise ValueError("static demo file paths must be unique")
        for item in self.files:
            if not isinstance(item, DemoFile):
                raise TypeError("static demo bundle requires typed files")
            item.__post_init__()
        if tuple(item["state"] for item in self.scenarios) != _STATES:
            raise ValueError(
                "static demo scenarios must use the frozen lifecycle order"
            )

    @property
    def manifest_bytes(self) -> bytes:
        return _canonical_bytes(
            {
                "demoVersion": self.demo_version,
                "synthetic": True,
                "files": tuple(item.to_manifest_entry() for item in self.files),
                "scenarios": self.scenarios,
                "verifiedClaims": self.verified_claims,
                "explicitNonClaims": self.explicit_non_claims,
            }
        )

    @property
    def bundle_id(self) -> str:
        return _digest(self.manifest_bytes)

    @property
    def all_files(self) -> tuple[DemoFile, ...]:
        manifest = DemoFile.create(
            "manifest.json", "application/json", self.manifest_bytes
        )
        checksum_lines = tuple(
            f"{item.body_sha256.removeprefix('sha256:')}  {item.path}"
            for item in (*self.files, manifest)
        )
        checksums = DemoFile.create(
            "checksums.txt",
            "text/plain; charset=utf-8",
            ("\n".join(checksum_lines) + "\n").encode("utf-8"),
        )
        return (*self.files, manifest, checksums)

    def write_directory(self, directory: Path) -> None:
        if not isinstance(directory, Path):
            raise TypeError("demo output must be a pathlib.Path")
        resolved = directory.resolve()
        if resolved in {Path("/").resolve(), Path.home().resolve()}:
            raise ValueError("refusing broad demo output directory")
        if resolved.exists() and (not resolved.is_dir() or any(resolved.iterdir())):
            raise ValueError("demo output directory must be absent or empty")
        resolved.mkdir(parents=True, exist_ok=True)
        for item in self.all_files:
            target = resolved.joinpath(*PurePosixPath(item.path).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(item.body)
        self.verify_directory(resolved)

    def verify_directory(self, directory: Path) -> str:
        if not isinstance(directory, Path):
            raise TypeError("demo output must be a pathlib.Path")
        resolved = directory.resolve()
        if not resolved.is_dir():
            raise ValueError("demo output directory does not exist")
        observed: dict[str, bytes] = {}
        for path in sorted(resolved.rglob("*")):
            if path.is_symlink():
                raise ValueError("demo output may not contain symbolic links")
            if path.is_file():
                relative = path.relative_to(resolved).as_posix()
                observed[relative] = path.read_bytes()
        expected = {item.path: item.body for item in self.all_files}
        if observed.keys() != expected.keys():
            raise ValueError("demo output file set mismatch")
        for path, body in expected.items():
            if observed[path] != body:
                raise ValueError(f"demo output byte mismatch: {path}")
        return self.bundle_id


class StaticDemoCompiler:
    """Compile exact M6B/M6C synthetic sites into a static public bundle."""

    def compile(self, sites: Mapping[str, PrototypeSite]) -> StaticDemoBundle:
        if not isinstance(sites, Mapping) or tuple(sites) != _STATES:
            raise ValueError("demo requires the four frozen lifecycle sites in order")
        files: list[DemoFile] = [
            DemoFile.create(".nojekyll", "application/octet-stream", b""),
            DemoFile.create(
                "index.html",
                "text/html; charset=utf-8",
                self._landing_page().encode("utf-8"),
            ),
        ]
        scenarios: list[dict[str, str]] = []
        for state in _STATES:
            site = sites[state]
            if not isinstance(site, PrototypeSite):
                raise TypeError("demo scenarios require typed PrototypeSite values")
            report = SyntheticComprehensionInstrument().qualify(site)
            if report.verdict is not ComprehensionVerdict.INFORMATION_SUFFICIENT:
                raise ValueError(
                    "demo scenario lacks synthetic explanatory information"
                )
            ordinary = site.ordinary_feed.to_bytes()
            audit = site.audit_feed.to_bytes()
            files.extend(
                (
                    DemoFile.create(
                        f"{state}/index.html",
                        "text/html; charset=utf-8",
                        site.ordinary_html.encode("utf-8"),
                    ),
                    DemoFile.create(
                        f"{state}/audit.html",
                        "text/html; charset=utf-8",
                        site.audit_html.encode("utf-8"),
                    ),
                    DemoFile.create(f"{state}/feed.json", "application/json", ordinary),
                    DemoFile.create(
                        f"{state}/audit-feed.json", "application/json", audit
                    ),
                )
            )
            scenarios.append(
                {
                    "state": state,
                    "siteId": site.site_id,
                    "ordinaryFeedId": site.ordinary_feed.feed_id,
                    "auditFeedId": site.audit_feed.feed_id,
                    "comprehensionReportId": report.report_id,
                }
            )
        return StaticDemoBundle(files=tuple(files), scenarios=tuple(scenarios))

    def _landing_page(self) -> str:
        cards = "".join(
            (
                f'<li><a href="{escape(state)}/">'
                f"<strong>{escape(_STATE_TITLES[state])}</strong>"
                "<span>Open the ordinary reader view</span></a></li>"
            )
            for state in _STATES
        )
        return (
            '<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            "<title>Portable community projection demo</title><style>"
            ":root{color-scheme:light dark}body{font:17px/1.55 system-ui;"
            "max-width:54rem;margin:3rem auto;padding:0 1.25rem}"
            "h1{line-height:1.1}.notice{border-left:.35rem solid #7c5cff;"
            "padding:.8rem 1rem;background:color-mix(in srgb,#7c5cff 12%,transparent)}"
            "ul{list-style:none;padding:0;display:grid;gap:1rem}"
            "li a{display:flex;flex-direction:column;border:1px solid #888;"
            "border-radius:.7rem;padding:1rem;text-decoration:none;color:inherit}"
            "li a:hover{border-color:#7c5cff}li span{opacity:.75}code{font-size:.9em}"
            "</style></head><body><main><p>SCV0 synthetic product experiment</p>"
            "<h1>A community owns inclusion. The renderer is only the window.</h1>"
            '<div class="notice"><strong>Synthetic demo.</strong> No live ATProto '
            "account, private Space data, credential, or human activity appears here.</div>"
            "<p>Each example is the same author-owned reference at a different community "
            "projection lifecycle state. Open a card, then use <em>Why is this here?</em> "
            "to inspect the separate audit view.</p>"
            f"<ul>{cards}</ul>"
            '<p><a href="manifest.json">Bundle manifest</a> · '
            '<a href="checksums.txt">Checksums</a></p>'
            "<p>This publication does not establish source truth, reader permission, "
            "membership, governance authority, or production readiness.</p>"
            "</main></body></html>"
        )


def _technical_receipts(*, removed: bool) -> ArtifactReceiptReferences:
    return ArtifactReceiptReferences(
        source_qualification_receipt_id="sha256:" + "6" * 64,
        source_observation_receipt_id="sha256:" + "7" * 64,
        source_currentness_receipt_id="sha256:" + "8" * 64,
        submission_evidence_receipt_id="sha256:" + "9" * 64,
        moderator_authorization_id="sha256:" + "a" * 64,
        admission_id="sha256:" + "4" * 64,
        projection_reference_id="sha256:" + "b" * 64,
        removal_id="sha256:" + "5" * 64 if removed else None,
    )


def build_synthetic_demo_sites() -> dict[str, PrototypeSite]:
    """Build the fixed public demo corpus without network, identity, or secrets."""

    community_id = "sha256:" + "1" * 64
    space_id = "sha256:" + "2" * 64
    projection_id = "sha256:" + "3" * 64
    admission_id = "sha256:" + "4" * 64
    removal_id = "sha256:" + "5" * 64
    post_id = "sha256:33981b56015a979c8f4333d2ae46aa2cdc7f00090a2dbca4e1f23aed18560688"
    presentation = BoundedSourcePresentation(
        source_reference_id=post_id,
        source_uri=(
            "at://did:web:author.invalid.test/test.invalid.community.post/tool-library"
        ),
        source_cid="bafyreicj4w5qcnzob6gqff7ydadwzgbkh4r3p5xozr5pj4f7ke5ybjqr5i",
        title="Neighborhood tool library opens Saturday",
        body=(
            "A synthetic author-owned post about lending garden tools. "
            "The community decides only whether to include the reference."
        ),
        author_display_reference="@author.invalid.test",
    )
    policies = {
        False: DisclosurePolicy(
            mode=DisclosureMode.ORDINARY,
            policy_reference_id="sha256:" + "c" * 64,
            publication_reference_id="sha256:" + "d" * 64,
        ),
        True: DisclosurePolicy(
            mode=DisclosureMode.TECHNICAL_AUDIT,
            policy_reference_id="sha256:" + "e" * 64,
            publication_reference_id="sha256:" + "f" * 64,
        ),
    }

    def artifact(state: str, *, audit: bool) -> ProjectionArtifact:
        removed = state == "removed"
        policy = policies[audit]
        entry = ProjectionArtifactEntry(
            projection_identity=projection_id,
            projection_state_id=(
                "sha256:"
                + {
                    "added": "1",
                    "changed_at_source": "2",
                    "source_unavailable": "3",
                    "removed": "4",
                }[state]
                * 64
            ),
            lifecycle_state=state,
            community_identity_id=community_id,
            post_reference_id=post_id,
            source_uri=presentation.source_uri,
            admitted_source_cid=presentation.source_cid,
            author_did="did:web:author.invalid.test",
            admission_id=admission_id,
            admitted_at="2026-08-22T12:00:00Z",
            source_observation_id="sha256:" + "0" * 64,
            source_relationship={
                "added": "exact",
                "changed_at_source": "changed_at_source",
                "source_unavailable": "unavailable",
                "removed": "exact",
            }[state],
            presentation=presentation if state == "added" else None,
            technical_receipts=(
                _technical_receipts(removed=removed) if audit else None
            ),
            available_lifecycle_links=(
                ("sha256:" + "1" * 64, "sha256:" + "2" * 64) if audit else ()
            ),
            removal_id=removal_id if removed else None,
        )
        return ProjectionArtifact(
            community_identity_id=community_id,
            community_actor_did="did:web:community.invalid.test",
            space_identity_id=space_id,
            projection_version="scv0-projection-reducer/1",
            disclosure_mode=policy.mode,
            disclosure_policy_id=policy.policy_id,
            disclosure_policy_reference_id=policy.policy_reference_id,
            publication_reference_id=policy.publication_reference_id,
            entries=(entry,),
        )

    def publish(state: str, *, audit: bool):
        item = artifact(state, audit=audit)
        return LocalProjectionFeedBoundary().publish(
            FeedPublicationRequest(
                artifact=item,
                expected_artifact_id=item.artifact_id,
                expected_community_identity_id=item.community_identity_id,
                expected_publication_reference_id=item.publication_reference_id,
                channel=(
                    PublicProjectionChannel.TECHNICAL_AUDIT
                    if audit
                    else PublicProjectionChannel.ORDINARY
                ),
                published_at=(
                    "2026-08-22T16:00:01Z" if audit else "2026-08-22T16:00:00Z"
                ),
            )
        )

    prototype = LocalCommunityPrototype()
    return {
        state: prototype.render(publish(state, audit=False), publish(state, audit=True))
        for state in _STATES
    }
