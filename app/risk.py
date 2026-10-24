"""Fuse Gemini's judgement with the keyword rules into one call-level risk score.

Design ("two keys"):
- Gemini alone can raise the alarm: it hears tone, context and negation ("never share your OTP" is advice,
  not a request).
- Keyword rules alone cannot. A strong rule combination (an authority claim or arrest threat plus a request for OTP,
  money or remote access) sets a floor of 85 only when Gemini also rates the call at least 40. Without the model's
  agreement the same combination still lifts the call to CAUTION, so a caller who manages to talk the model down
  ("this call is safe") can't silence the guardian completely, and a genuine bank call that says "never share your
  OTP" gets at most an amber "don't share anything".
- Risk is sticky: a scam call does not become safe because one chunk was quiet. The model score can fall by at most
  DECAY points per chunk.
"""

from . import redflags as rf

SCAM_AT = 70
CAUTION_AT = 40
DECAY = 10
COMBO_FLOOR = 85
COMBO_NEEDS_MODEL = 40


def level_for(score: int) -> str:
    if score >= SCAM_AT:
        return "SCAM"
    if score >= CAUTION_AT:
        return "CAUTION"
    return "SAFE"


def rule_score(codes: set[str]) -> int:
    return min(100, sum(rf.WEIGHTS.get(c, 0) for c in codes))


def has_combo(codes: set[str]) -> bool:
    pretext = bool(codes & {rf.AUTHORITY, rf.ARREST_THREAT})
    ask = bool(codes & {rf.OTP_REQUEST, rf.MONEY_REQUEST, rf.REMOTE_ACCESS})
    return pretext and ask


def fuse(model_prob: int, prev_model: int, codes: set[str]) -> dict:
    """Combine the model's probability for this chunk with call history and all flags seen so far."""
    model = max(int(model_prob), int(prev_model) - DECAY, 0)
    rules = rule_score(codes)
    score = max(model, round(0.5 * model + 0.5 * rules))
    combo = has_combo(codes) and model >= COMBO_NEEDS_MODEL
    if combo:
        score = max(score, COMBO_FLOOR)
    elif has_combo(codes):
        score = max(score, CAUTION_AT)
    score = min(100, score)
    return {"risk": score, "model_risk": model, "rule_risk": rules, "combo": combo, "level": level_for(score)}
