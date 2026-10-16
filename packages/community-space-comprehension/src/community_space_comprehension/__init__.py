"""Synthetic product-comprehension checks for the SCV0 local prototype."""

from .instrument import (
    INSTRUMENT_VERSION,
    ComprehensionVerdict,
    SyntheticComprehensionInstrument,
    SyntheticComprehensionReport,
    SyntheticQuestionOutcome,
    refuse_comprehension_claim_upgrade,
)

__all__ = [
    "INSTRUMENT_VERSION",
    "ComprehensionVerdict",
    "SyntheticComprehensionInstrument",
    "SyntheticComprehensionReport",
    "SyntheticQuestionOutcome",
    "refuse_comprehension_claim_upgrade",
]

__version__ = "0.1.0"
