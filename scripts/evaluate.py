"""Replay every sample call through the real pipeline (Gemini + rules + fusion), exactly as the browser does, and
report whether Sajag got it right and how early it warned.

Usage:  uv run python scripts/evaluate.py [--chunk 5] [--lang gu]
Needs GEMINI_API_KEY. Writes eval-results.json and prints a Markdown table you can paste into docs/EVALUATION.md.
"""

import argparse
import asyncio
import json
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import analyzer, config, pipeline, risk
from app.speech import pcm_to_wav  # noqa: E402


def chunks(path: Path, seconds: float):
    with wave.open(str(path)) as w:
        rate, width = w.getframerate(), w.getsampwidth()
        pcm = w.readframes(w.getnframes())
    step = int(rate * seconds) * width
    for i in range(0, len(pcm), step):
        part = pcm[i : i + step]
        if len(part) < rate * width * 0.8:
            continue
        t0 = i / width / rate
        yield t0, t0 + len(part) / width / rate, pcm_to_wav(part, rate)


async def run_call(path: Path, lang: str, seconds: float) -> dict:
    transcript, flags, model_risk = "", [], 0
    warned_at, peak, timeline, latencies = None, 0, [], []
    duration = 0.0
    for t0, t1, wav in chunks(path, seconds):
        duration = t1
        v = await analyzer.analyze_chunk(wav, "audio/wav", lang, transcript, flags, t0, t1)
        latencies.append(v["latency_ms"])
        fused = pipeline.assess(v, flags, model_risk)  # exactly what the API does for each chunk
        flags, model_risk = fused["all_flags"], fused["model_risk"]
        peak = max(peak, fused["risk"])
        if v["transcript"]:
            transcript += ("\n" if transcript else "") + v["transcript"]
        if fused["level"] == "SCAM" and warned_at is None:
            warned_at = t1
        timeline.append({"t": round(t1, 1), "risk": fused["risk"], "level": fused["level"], "flags": flags})
    return {
        "duration": round(duration, 1),
        "warned_at": warned_at,
        "peak": peak,
        "flags": sorted(flags),
        "final": risk.level_for(peak),
        "avg_latency_ms": round(sum(latencies) / max(1, len(latencies))),
        "timeline": timeline,
        "transcript": transcript,
    }


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunk", type=float, default=5.0)
    ap.add_argument("--lang", default="gu", choices=["gu", "hi", "en"])
    args = ap.parse_args()
    if not config.GEMINI_API_KEY:
        sys.exit("GEMINI_API_KEY is not set (put it in .env)")

    results = {}
    print(f"model={config.MODEL} chunk={args.chunk}s\n")
    print("| Call | Expected | Sajag | Warned at | Red flags | Avg latency |")
    print("|---|---|---|---|---|---|")
    for meta_path in sorted((config.SAMPLES_DIR / "scripts").glob("*.json")):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        started = time.perf_counter()
        r = await run_call(config.SAMPLES_DIR / f"{meta_path.stem}.wav", args.lang, args.chunk)
        r["expected"] = meta["expected"]
        r["correct"] = (r["final"] == "SCAM") == (meta["expected"] == "SCAM")
        r["wall_s"] = round(time.perf_counter() - started, 1)
        results[meta_path.stem] = r
        warned = f"{r['warned_at']:.0f}s of {r['duration']:.0f}s" if r["warned_at"] else "never"
        mark = "✅" if r["correct"] else "❌"
        print(
            f"| {meta_path.stem} | {meta['expected']} | {mark} {r['final']} (peak {r['peak']}) | {warned} | "
            f"{', '.join(r['flags']) or '–'} | {r['avg_latency_ms'] / 1000:.1f}s |"
        )
    Path("eval-results.json").write_text(
        json.dumps({"model": config.MODEL, "chunk": args.chunk, "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    correct = sum(r["correct"] for r in results.values())
    print(f"\n{correct}/{len(results)} calls classified correctly. Details: eval-results.json")


if __name__ == "__main__":
    asyncio.run(main())
