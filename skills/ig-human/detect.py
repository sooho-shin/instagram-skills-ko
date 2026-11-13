#!/usr/bin/env python3
"""
detect.py - a five-check panel that scores how machine-written a draft looks.

What this is:  five local heuristics modelled on the signals public AI
detectors actually measure - sentence-length variation, concreteness, stock
vocabulary, typographic fingerprint, and voice. Every score is computed on
your machine from the text alone. Nothing is uploaded.

What this is NOT:  GPTZero, Originality, Copyleaks, Winston or Turnitin.
It does not call their APIs and it cannot promise their verdict. It catches
the things they all key on, which is why fixing them tends to move their
numbers too - but the only honest claim is the one on this line.

Each check returns a HUMAN score from 0 to 100. Higher is better.

Usage
  python3 detect.py draft.txt
  pbpaste | python3 detect.py -
  python3 detect.py draft.txt --json
  python3 detect.py before.txt after.txt      # compare two drafts
"""

import argparse
import json
import os
import re
import statistics
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ko  # noqa: E402  Korean mode (local patch)

HERE = os.path.dirname(os.path.abspath(__file__))
LEX = os.path.join(HERE, "slop.json")

SENT_RE = re.compile(r"[^.!?\n]+[.!?]*")
WORD_RE = re.compile(r"[A-Za-z']+")
CONTRACTIONS = re.compile(r"\b\w+'(?:s|t|re|ve|ll|d|m)\b", re.IGNORECASE)
PRONOUNS = re.compile(r"\b(i|me|my|mine|we|us|our|you|your)\b", re.IGNORECASE)
NUMBERS = re.compile(r"\b\d[\d,.]*%?\b|\$\d")
PROPER = re.compile(r"(?<![.!?]\s)(?<!^)\b[A-Z][a-z]{2,}\b", re.MULTILINE)


def clamp(n):
    return max(0.0, min(100.0, n))


def scale(value, human, machine):
    """Map value onto 0-100 where `human` -> 100 and `machine` -> 0."""
    if human == machine:
        return 50.0
    return clamp((value - machine) / (human - machine) * 100)


def sentences(text):
    return [s.strip() for s in SENT_RE.findall(text) if len(s.split()) > 2]


def words(text):
    return WORD_RE.findall(text)


def check_burstiness(text, korean=False):
    """Humans vary sentence length hard. Models write even."""
    if korean:
        lens = [ko.syl_len(s) for s in ko.sentences(text)]
    else:
        lens = [len(s.split()) for s in sentences(text)]
    if len(lens) < 4:
        return 50.0, ("문장이 4개 미만이라 판단 보류" if korean else "too short to judge")
    mean = statistics.mean(lens)
    cv = statistics.pstdev(lens) / mean if mean else 0
    score = scale(cv, human=0.70, machine=0.22)
    if korean:
        return score, f"문장 {len(lens)}개, 음절 길이 변동 {cv:.2f} (0.55 이상 권장)"
    return score, f"variation {cv:.2f} across {len(lens)} sentences (want 0.55+)"


def check_specificity(text, korean=False):
    """Numbers, names and concrete nouns. Slop is abstract."""
    if korean:
        # Hangul names cannot be told from common nouns, so this counts
        # figures (17도, 3가지, 7시) and Latin brand names only.
        u = ko.units(text)
        if len(u) < 15:
            return 50.0, "어절 15개 미만이라 판단 보류"
        hits = len(ko.NUMBER_RE.findall(text)) + len(set(ko.BRAND_RE.findall(text)))
        density = hits * 100 / len(u)
        score = scale(density, human=8.0, machine=1.0)
        return score, f"숫자·고유명사 {hits}개, 100어절당 {density:.1f} (5 이상 권장)"
    w = words(text)
    if len(w) < 25:
        return 50.0, "too short to judge"
    per100 = 100 / len(w)
    hits = len(NUMBERS.findall(text)) + len(set(PROPER.findall(text)))
    density = hits * per100
    score = scale(density, human=6.0, machine=0.5)
    return score, f"{hits} concrete markers, {density:.1f} per 100 words (want 4+)"


def check_slop(text, lex, korean=False):
    """Stock vocabulary density against the lexicon."""
    w = ko.units(text) if korean else words(text)
    if not w:
        return 50.0, "empty"
    hits, found = 0, []
    for entry in lex["words"] + lex["phrases"]:
        n = len(ko.term_pattern(entry).findall(text))
        if n:
            hits += n
            found.append(entry["find"])
    density = hits * 100 / len(w)
    score = scale(density, human=0.0, machine=5.0 if korean else 4.0)
    detail = (f"상투어 {hits}개, 100어절당 {density:.1f}" if korean
              else f"{hits} stock terms, {density:.1f} per 100 words")
    if found:
        detail += " (" + ", ".join(sorted(found)[:4]) + (", ..." if len(found) > 4 else "") + ")"
    return score, detail


def check_fingerprint(text):
    """Characters a phone keyboard does not produce."""
    invisible = sum(1 for c in text if unicodedata.category(c) == "Cf")
    em = text.count("—")
    curly = sum(text.count(c) for c in "‘’“”")
    ellip = text.count("…")
    nbsp = sum(text.count(c) for c in "   ")
    total = invisible * 4 + em * 2 + curly + ellip + nbsp
    per1k = total * 1000 / max(len(text), 1)
    score = scale(per1k, human=0.0, machine=12.0)
    detail = (f"{invisible} invisible, {em} em dash, {curly} curly quote, "
              f"{ellip} ellipsis, {nbsp} hard space")
    return score, detail


def structure_tells(text, lex):
    tells, names = 0, []
    for s in lex["structures"]:
        try:
            n = len(re.compile(s["regex"], re.MULTILINE).findall(text))
        except re.error:
            continue
        if n:
            tells += n
            names.append(s["id"])
    return tells, names


def check_voice_ko(text, lex):
    """Korean voice: 합쇼체 share, casual markers, structural tells.

    Korean drops pronouns, so pronoun density says nothing here. What gives a
    machine away is an Instagram caption written entirely in 습니다/입니다 with
    no 진짜, 근데 or ㅋㅋ anywhere.
    """
    u = ko.units(text)
    if len(u) < 15:
        return 50.0, "어절 15개 미만이라 판단 보류"
    sents = ko.sentences(text)
    formal = sum(1 for s in sents if ko.is_formal(s))
    formal_ratio = formal / len(sents) if sents else 0
    casual = ko.colloquial_hits(text, lex.get("colloquial", [])) * 100 / len(u)
    tells, names = structure_tells(text, lex)
    score = (scale(formal_ratio, human=0.0, machine=0.7) * 0.35
             + scale(casual, human=4.0, machine=0.0) * 0.35
             + clamp(100 - tells * 22) * 0.30)
    detail = (f"합쇼체 문장 {formal}/{len(sents)}, 구어 표현 100어절당 {casual:.1f}, "
              f"구조 패턴 {tells}개")
    if names:
        detail += " [" + ", ".join(names[:4]) + "]"
    return clamp(score), detail


def check_voice(text, lex, korean=False):
    """Contractions, person, and the shapes models default to."""
    if korean:
        return check_voice_ko(text, lex)
    w = words(text)
    if len(w) < 25:
        return 50.0, "too short to judge"
    per100 = 100 / len(w)
    contractions = len(CONTRACTIONS.findall(text)) * per100
    person = len(PRONOUNS.findall(text)) * per100
    tells = 0
    names = []
    for s in lex["structures"]:
        try:
            n = len(re.compile(s["regex"], re.MULTILINE).findall(text))
        except re.error:
            continue
        if n:
            tells += n
            names.append(s["id"])
    bullets = [len(b.split()) for b in re.findall(r"(?m)^\s*[-*•]\s+(.+)$", text)]
    uniform = (len(bullets) >= 3 and statistics.pstdev(bullets) < 1.6)
    score = (scale(contractions, human=3.0, machine=0.0) * 0.35
             + scale(person, human=8.0, machine=1.0) * 0.35
             + clamp(100 - tells * 22) * 0.30)
    if uniform:
        score -= 12
        names.append("uniform-bullets")
    detail = (f"{contractions:.1f} contractions, {person:.1f} personal pronouns "
              f"per 100 words, {tells} structural tell(s)")
    if names:
        detail += " [" + ", ".join(names[:4]) + "]"
    return clamp(score), detail


CHECKS = ["BURSTINESS", "SPECIFICITY", "SLOP DENSITY", "FINGERPRINT", "VOICE"]


def run(text, lex):
    korean = ko.is_korean(text)
    results = {}
    results["BURSTINESS"] = check_burstiness(text, korean)
    results["SPECIFICITY"] = check_specificity(text, korean)
    results["SLOP DENSITY"] = check_slop(text, lex, korean)
    results["FINGERPRINT"] = check_fingerprint(text)
    results["VOICE"] = check_voice(text, lex, korean)
    scores = [results[c][0] for c in CHECKS]
    results["_korean"] = korean
    # The weakest check drags the verdict: a detector only needs one signal.
    overall = statistics.mean(scores) * 0.6 + min(scores) * 0.4
    verdict = "PASS" if overall >= 70 and min(scores) >= 55 else (
        "REVIEW" if overall >= 50 else "FLAGGED")
    return results, overall, verdict


def bar(score, width=24):
    filled = round(score / 100 * width)
    return "#" * filled + "." * (width - filled)


def render(results, overall, verdict, label=None, out=sys.stdout):
    title = "AI DETECTION PANEL" + (f"  -  {label}" if label else "")
    if results.get("_korean"):
        title += "  [한국어 모드]"
    print("\n" + title, file=out)
    print("=" * max(len(title), 62), file=out)
    for name in CHECKS:
        score, detail = results[name]
        print(f"  {name:<13} {bar(score)} {score:5.1f}", file=out)
        print(f"  {'':<13} {detail}", file=out)
    print("-" * 62, file=out)
    print(f"  {'HUMAN SCORE':<13} {bar(overall)} {overall:5.1f}   {verdict}", file=out)
    if verdict != "PASS":
        weakest = min(CHECKS, key=lambda c: results[c][0])
        print(f"\n  Weakest signal: {weakest}. Fix that first.", file=out)
    print("", file=out)


def main():
    ap = argparse.ArgumentParser(description="Score how machine-written a draft looks.")
    ap.add_argument("input", nargs="?", default="-", help="file, or - for stdin")
    ap.add_argument("compare", nargs="?", help="second file, to show before/after")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--lexicon", default=LEX)
    args = ap.parse_args()

    lex = ko.merge(json.load(open(args.lexicon, encoding="utf-8")))
    read = lambda p: sys.stdin.read() if p == "-" else open(p, encoding="utf-8").read()

    targets = [(args.input, read(args.input))]
    if args.compare:
        targets.append((args.compare, read(args.compare)))

    payload = []
    for name, text in targets:
        results, overall, verdict = run(text, lex)
        payload.append({
            "source": name,
            "korean": results["_korean"],
            "checks": {k: {"score": round(results[k][0], 1), "detail": results[k][1]} for k in CHECKS},
            "human_score": round(overall, 1),
            "verdict": verdict,
        })

    if args.json:
        print(json.dumps(payload if args.compare else payload[0], indent=2, ensure_ascii=False))
        return

    for (name, text), p in zip(targets, payload):
        results, overall, verdict = run(text, lex)
        render(results, overall, verdict, label=os.path.basename(name) if args.compare else None)
    if args.compare:
        a, b = payload
        delta = b["human_score"] - a["human_score"]
        print(f"  {a['human_score']:.1f} {a['verdict']}  ->  "
              f"{b['human_score']:.1f} {b['verdict']}   ({delta:+.1f})\n")

    sys.exit(0 if payload[-1]["verdict"] == "PASS" else 1)


if __name__ == "__main__":
    main()
