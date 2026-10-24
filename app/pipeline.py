"""Turn one Gemini verdict into a call-level assessment. Shared by the API and the offline evaluation, so both score
calls exactly the same way."""

from collections.abc import Iterable
from typing import Any

from . import redflags as rf
from . import risk


def assess(verdict: dict[str, Any], prev_flags: Iterable[str], prev_model_risk: int) -> dict[str, Any]:
    """Add the keyword second opinion to Gemini's flags, then fuse everything seen so far into one risk level.

    Unknown codes in `prev_flags` (client state is untrusted) are ignored.
    """
    model_codes = {f["code"] for f in verdict["flags"]}
    rule_hits = [h for h in rf.match_rules(verdict["transcript"], verdict["english"]) if h["code"] not in model_codes]
    new_flags = [{**f, "source": "gemini"} for f in verdict["flags"]] + [{**h, "source": "rules"} for h in rule_hits]

    known_prev = {f for f in prev_flags if f in rf.CODES}
    all_codes = known_prev | {f["code"] for f in new_flags}
    fused = risk.fuse(verdict["scam_probability"], prev_model_risk, all_codes)
    return {"flags": new_flags, "all_flags": sorted(all_codes), **fused}
