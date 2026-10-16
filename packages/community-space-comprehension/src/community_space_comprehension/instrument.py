"""Fixture-only comprehension cues over exact canonical M6B pages.

This instrument establishes machine-recoverable interface information. It
does not simulate, predict, or measure a human reader.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from html.parser import HTMLParser
from typing import Final

from community_space_prototype import LocalCommunityPrototype, PrototypeSite

INSTRUMENT_VERSION: Final = "scv0-synthetic-comprehension/1"

_VERIFIED_CLAIMS: Final = (
    "canonical_prototype_replayed",
    "fixed_explanatory_cues_evaluated",
    "ordinary_audit_disclosure_separation_evaluated",
)

_NON_CLAIMS: Final = (
    "human_comprehension",
    "human_usability",
    "accessibility_conformance",
    "reader_authentication",
    "reader_authorization",
    "membership",
    "moderator_authority",
    "governance_authority",
    "source_truth",
    "source_ownership",
    "repository_currentness",
    "ranking",
)

_STATE_LABELS: Final = {
    "added": "Added",
    "changed_at_source": "Changed at source",
    "source_unavailable": "Source unavailable",
    "removed": "Removed",
}


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


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag.lower() in {"script", "style"}:
            self._hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style"} and self._hidden_depth:
            self._hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._hidden_depth and data.strip():
            self.parts.append(" ".join(data.split()))


def _visible_text(document: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(document)
    parser.close()
    return " ".join(parser.parts)


class ComprehensionVerdict(StrEnum):
    INFORMATION_SUFFICIENT = "synthetic_information_sufficient"
    INFORMATION_INSUFFICIENT = "synthetic_information_insufficient"


@dataclass(frozen=True, slots=True)
class SyntheticQuestionOutcome:
    question_id: str
    prompt: str
    expected_interpretation: str
    observed_cues: tuple[str, ...]
    answerable: bool

    def __post_init__(self) -> None:
        if not self.question_id or not self.prompt or not self.expected_interpretation:
            raise ValueError("synthetic question fields must be non-empty")
        if not isinstance(self.observed_cues, tuple) or not all(
            isinstance(item, str) and item for item in self.observed_cues
        ):
            raise ValueError("observed cues must be a tuple of non-empty strings")

    def to_payload(self) -> dict[str, object]:
        return {
            "questionId": self.question_id,
            "prompt": self.prompt,
            "expectedInterpretation": self.expected_interpretation,
            "observedCues": self.observed_cues,
            "answerable": self.answerable,
        }


@dataclass(frozen=True, slots=True)
class SyntheticComprehensionReport:
    prototype_site_id: str
    ordinary_html_sha256: str
    audit_html_sha256: str
    outcomes: tuple[SyntheticQuestionOutcome, ...]
    verdict: ComprehensionVerdict | str
    verified_claims: tuple[str, ...] = _VERIFIED_CLAIMS
    explicit_non_claims: tuple[str, ...] = _NON_CLAIMS
    instrument_version: str = INSTRUMENT_VERSION

    def __post_init__(self) -> None:
        if self.instrument_version != INSTRUMENT_VERSION:
            raise ValueError("unsupported synthetic comprehension instrument version")
        if self.verified_claims != _VERIFIED_CLAIMS:
            raise ValueError("synthetic comprehension claims are fixed")
        if self.explicit_non_claims != _NON_CLAIMS:
            raise ValueError("synthetic comprehension non-claims are fixed")
        if not self.outcomes:
            raise ValueError("synthetic comprehension report needs question outcomes")
        if len({item.question_id for item in self.outcomes}) != len(self.outcomes):
            raise ValueError("synthetic comprehension question IDs must be unique")
        try:
            verdict = ComprehensionVerdict(self.verdict)
        except (TypeError, ValueError) as exc:
            raise ValueError("unsupported synthetic comprehension verdict") from exc
        object.__setattr__(self, "verdict", verdict)
        expected = (
            ComprehensionVerdict.INFORMATION_SUFFICIENT
            if all(item.answerable for item in self.outcomes)
            else ComprehensionVerdict.INFORMATION_INSUFFICIENT
        )
        if verdict is not expected:
            raise ValueError("synthetic comprehension verdict contradicts outcomes")

    @property
    def report_id(self) -> str:
        return _digest(_canonical_bytes(self.to_payload()))

    @property
    def answerable_question_ids(self) -> tuple[str, ...]:
        return tuple(item.question_id for item in self.outcomes if item.answerable)

    @property
    def unanswerable_question_ids(self) -> tuple[str, ...]:
        return tuple(item.question_id for item in self.outcomes if not item.answerable)

    def to_payload(self) -> dict[str, object]:
        return {
            "instrumentVersion": self.instrument_version,
            "prototypeSiteId": self.prototype_site_id,
            "ordinaryHtmlSha256": self.ordinary_html_sha256,
            "auditHtmlSha256": self.audit_html_sha256,
            "outcomes": tuple(item.to_payload() for item in self.outcomes),
            "verdict": self.verdict,
            "verifiedClaims": self.verified_claims,
            "explicitNonClaims": self.explicit_non_claims,
        }

    def validate_against(self, site: PrototypeSite) -> str:
        expected = SyntheticComprehensionInstrument().qualify(site)
        if self != expected:
            raise ValueError("synthetic comprehension report does not match exact site")
        return self.report_id


class SyntheticComprehensionInstrument:
    """Evaluate fixed explanatory questions without human/model inference."""

    def qualify(self, site: PrototypeSite) -> SyntheticComprehensionReport:
        if not isinstance(site, PrototypeSite):
            raise TypeError("synthetic comprehension requires a typed PrototypeSite")
        site.validate_integrity()
        replay = LocalCommunityPrototype().render(site.ordinary_feed, site.audit_feed)
        if replay != site:
            raise ValueError("prototype pages do not match canonical M6B replay")
        if len(site.canonical_semantics.entries) != 1:
            raise ValueError(
                "synthetic comprehension profile supports one lifecycle entry"
            )

        ordinary_text = _visible_text(site.ordinary_html)
        audit_text = _visible_text(site.audit_html)
        outcomes: list[SyntheticQuestionOutcome] = []
        for index, (ordinary_entry, audit_entry) in enumerate(
            zip(
                site.canonical_semantics.entries,
                site.audit_semantics.entries,
                strict=True,
            ),
            start=1,
        ):
            prefix = f"entry-{index}"
            state = ordinary_entry.lifecycle_state
            label = _STATE_LABELS[state]
            outcomes.extend(
                (
                    self._outcome(
                        f"{prefix}:lifecycle",
                        "What lifecycle state is this item in?",
                        label,
                        (label, ordinary_entry.lifecycle_notice),
                        ordinary_text,
                    ),
                    self._outcome(
                        f"{prefix}:community-inclusion",
                        "Why is this item on this community surface?",
                        "The community published its inclusion/lifecycle decision.",
                        (
                            "this community’s published inclusion and lifecycle decision",
                        ),
                        ordinary_text,
                    ),
                    self._outcome(
                        f"{prefix}:source-ownership",
                        "Did publication transfer ownership of the source?",
                        "No. The author still owns the source.",
                        ("The author still owns the source",),
                        ordinary_text,
                    ),
                    self._audit_outcome(prefix, audit_entry, audit_text),
                    self._separation_outcome(
                        prefix, audit_entry, ordinary_text, audit_text
                    ),
                    self._state_specific_outcome(prefix, ordinary_entry, ordinary_text),
                )
            )

        verdict = (
            ComprehensionVerdict.INFORMATION_SUFFICIENT
            if all(item.answerable for item in outcomes)
            else ComprehensionVerdict.INFORMATION_INSUFFICIENT
        )
        return SyntheticComprehensionReport(
            prototype_site_id=site.site_id,
            ordinary_html_sha256=site.ordinary_html_sha256,
            audit_html_sha256=site.audit_html_sha256,
            outcomes=tuple(outcomes),
            verdict=verdict,
        )

    def _outcome(
        self,
        question_id: str,
        prompt: str,
        expected: str,
        required_cues: tuple[str, ...],
        visible_text: str,
    ) -> SyntheticQuestionOutcome:
        observed = tuple(cue for cue in required_cues if cue in visible_text)
        return SyntheticQuestionOutcome(
            question_id=question_id,
            prompt=prompt,
            expected_interpretation=expected,
            observed_cues=observed,
            answerable=len(observed) == len(required_cues),
        )

    def _audit_outcome(self, prefix, entry, audit_text):
        references = tuple(value for _, value in entry.receipt_references)
        required = (
            "Receipt references",
            "Lifecycle chain",
            *references,
            *entry.lifecycle_links,
        )
        return self._outcome(
            f"{prefix}:auditability",
            "Can the disclosed technical references be inspected separately?",
            "Yes. The audit page exposes identifiers, not authority.",
            required,
            audit_text,
        )

    def _separation_outcome(self, prefix, entry, ordinary_text, audit_text):
        references = tuple(value for _, value in entry.receipt_references)
        audit_has_all = all(value in audit_text for value in references)
        ordinary_has_none = all(value not in ordinary_text for value in references)
        cues = tuple(
            item
            for item, present in (
                ("audit references present only in audit view", audit_has_all),
                ("ordinary view excludes audit references", ordinary_has_none),
            )
            if present
        )
        return SyntheticQuestionOutcome(
            question_id=f"{prefix}:disclosure-separation",
            prompt="Did technical audit disclosure leak into the ordinary view?",
            expected_interpretation="No. Ordinary and audit disclosures remain separate.",
            observed_cues=cues,
            answerable=len(references) > 0 and audit_has_all and ordinary_has_none,
        )

    def _state_specific_outcome(self, prefix, entry, ordinary_text):
        state = entry.lifecycle_state
        if state == "added":
            required = tuple(
                value
                for value in (entry.title, entry.body, entry.author_display_reference)
                if value is not None
            )
            expected = "The admitted bounded presentation is displayed."
        elif state == "changed_at_source":
            required = ("admitted presentation was not replaced",)
            expected = "The source changed; this is not a new admission or replacement."
        elif state == "source_unavailable":
            required = ("previously admitted source is currently unavailable",)
            expected = "The source is unavailable; the community did not remove it."
        elif state == "removed":
            required = ("author source was not mutated",)
            expected = (
                "The community projection was removed; the source was not deleted."
            )
        else:  # pragma: no cover - canonical M6B rejects unknown lifecycle states
            raise ValueError("unsupported lifecycle state")
        presentation_absent_when_required = state == "added" or (
            entry.title is None
            and entry.body is None
            and entry.author_display_reference is None
        )
        outcome = self._outcome(
            f"{prefix}:state-distinction",
            "What changed at the source/community boundary?",
            expected,
            required,
            ordinary_text,
        )
        if not presentation_absent_when_required:
            return SyntheticQuestionOutcome(
                question_id=outcome.question_id,
                prompt=outcome.prompt,
                expected_interpretation=outcome.expected_interpretation,
                observed_cues=outcome.observed_cues,
                answerable=False,
            )
        return outcome


def refuse_comprehension_claim_upgrade(labels: object) -> None:
    """Synthetic cue recovery cannot become a human or authority claim."""

    if not isinstance(labels, dict) or any(not isinstance(key, str) for key in labels):
        raise TypeError("synthetic comprehension labels must be an object")
    if labels:
        raise ValueError(
            "synthetic comprehension cannot add human, usability, or authority claims"
        )
