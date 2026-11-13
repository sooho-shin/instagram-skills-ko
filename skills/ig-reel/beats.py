#!/usr/bin/env python3
"""
beats.py - turn a Reel script into a timed beat sheet before you record it.

Estimates how long each line takes to say, stacks them into timecodes, and
flags the four things that kill a Reel in the edit: a hook that runs past the
three-second mark, a beat long enough for the viewer to leave, a run of lines
with nothing concrete in them, and a total length that does not match what you
said you were making.

The timings are an estimate from word count at a words-per-minute rate. They
are close enough to plan an edit and not a substitute for recording it. Set
your own rate with --wpm once you have timed yourself reading a script out
loud: most people land between 150 and 200, and the default here is 165.

Usage
  python3 beats.py script.txt
  python3 beats.py script.txt --target 30
  python3 beats.py script.txt --wpm 185 --target 45
  pbpaste | python3 beats.py -
  python3 beats.py script.txt --json
"""

import argparse
import json
import re
import sys

WORD_RE = re.compile(r"[A-Za-z0-9$%'’-]+")
SENT_RE = re.compile(r"[^.!?]+[.!?]*")
# Digits count wherever they sit: in Korean "10분씩" has no word boundary
# between the figure and its unit.
CONCRETE_RE = re.compile(
    r"\$\s?\d|(?<![\d,.])\d[\d,.]*|(?<!^)\b[A-Z][a-z]{2,}\b"
    r"|(?:두|세|네|다섯|여섯|일곱|여덟|아홉|열|스무|서른|마흔|쉰)\s"
    r"(?:초|분|시간|일|주|달|개월|년|번|개|명|배|벌|켤레|가지|살)"
    r"|(?:백|천|만|억)\s?원|절반|두\s?배|반값", re.MULTILINE)

# Korean is timed by syllable, not by word. Most people talking to camera
# land between 5.5 and 7 syllables a second; set yours with --sps.
HANGUL_RE = re.compile(r"[가-힣]")
KO_TOKEN_RE = re.compile(r"[가-힣]+")
KO_PARTICLES = sorted([
    "은", "는", "이", "가", "을", "를", "에", "에서", "에게", "도", "만", "으로",
    "로", "의", "와", "과", "랑", "이랑", "까지", "부터", "요", "처럼", "마다", "씩",
], key=len, reverse=True)
KO_STOPWORDS = {
    "이제", "진짜", "그냥", "그리고", "근데", "그래서", "저", "제", "제가", "내가",
    "나", "저는", "나는", "이", "그", "이거", "그거", "너무", "정말", "지금", "좀",
    "더", "다", "또", "안", "못", "것", "거", "수", "때", "하", "해", "했",
}
STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "of", "to", "in", "on", "for",
    "with", "that", "this", "it", "is", "are", "was", "were", "be", "been",
    "you", "your", "i", "my", "me", "we", "our", "they", "them", "he", "she",
    "so", "just", "not", "no", "do", "did", "does", "have", "has", "had",
    "will", "can", "at", "as", "by", "from", "out", "up", "off", "one", "all",
}

HOOK_WINDOW = 3.0        # seconds. Past this, the thumb has already decided.
MAX_BEAT = 4.0           # seconds on one idea with no change on screen.
ABSTRACT_RUN = 3         # beats in a row with nothing checkable in them.


def words(text):
    # "$18,000" is one word when it is spoken, so it is one word here too.
    return WORD_RE.findall(re.sub(r"(?<=\d),(?=\d)", "", text))


def syllables(text):
    return len(HANGUL_RE.findall(text))


def seconds(text, wps, sps):
    """Latin words at the word rate, Hangul at the syllable rate."""
    return len(words(text)) / wps + syllables(text) / sps


def ko_stems(text):
    """Strip one trailing particle so "비가" and "비" count as the same word."""
    out = set()
    for tok in KO_TOKEN_RE.findall(text):
        for p in KO_PARTICLES:
            if tok.endswith(p) and len(tok) > len(p):
                tok = tok[:-len(p)]
                break
        if tok not in KO_STOPWORDS:
            out.add(tok)
    return out


def pretty(token):
    """Put the thousands separator back for display."""
    return re.sub(r"(\d)(?=(\d{3})+$)", r"\1,", token)


def tc(seconds):
    m, s = divmod(seconds, 60)
    return f"{int(m)}:{s:04.1f}"


def split_beats(raw, wps, sps):
    """One line is one beat, unless a line is too long to be one."""
    beats = []
    for line in [l.strip() for l in raw.splitlines()]:
        if not line:
            continue
        if seconds(line, wps, sps) <= MAX_BEAT * 1.5:
            beats.append(line)
            continue
        # Long paragraph: break it at sentence ends so the timings mean
        # something, and let the report say it was split.
        parts = [p.strip() for p in SENT_RE.findall(line) if p.strip()]
        buf = ""
        for part in parts:
            candidate = (buf + " " + part).strip()
            if buf and seconds(candidate, wps, sps) > MAX_BEAT:
                beats.append(buf)
                buf = part
            else:
                buf = candidate
        if buf:
            beats.append(buf)
    return beats


def analyse(raw, wpm=165, target=None, sps=6.0):
    wps = wpm / 60.0
    beats = split_beats(raw, wps, sps)
    if not beats:
        return None
    korean = syllables(raw) * 2.5 >= len(re.findall(r"[A-Za-z]", raw)) and syllables(raw) > 0

    rows, clock = [], 0.0
    for i, text in enumerate(beats):
        n = len(words(text))
        dur = seconds(text, wps, sps)
        rows.append({
            "n": i + 1,
            "start": round(clock, 2),
            "dur": round(dur, 2),
            "words": n,
            "syllables": syllables(text),
            "text": text,
            "concrete": len(CONCRETE_RE.findall(text)),
            "label": "",
            "flags": [],
        })
        clock += dur
    total = clock

    # Label the structural positions a Reel is actually built around.
    for r in rows:
        if r["n"] == 1 or r["start"] + r["dur"] <= HOOK_WINDOW:
            r["label"] = "HOOK"
    rows[-1]["label"] = "CTA" if rows[-1]["label"] != "HOOK" else "HOOK/CTA"
    half = total / 2
    for r in rows:
        if not r["label"] and r["start"] <= half < r["start"] + r["dur"]:
            r["label"] = "MID"

    notes = []
    if rows[0]["dur"] > HOOK_WINDOW:
        rows[0]["flags"].append(f"hook runs {rows[0]['dur']:.1f}s, past the {HOOK_WINDOW:.0f}s mark")
        limit = (f"{int(HOOK_WINDOW * sps)} syllables" if korean
                 else f"{int(HOOK_WINDOW * wps)} words")
        notes.append(f"Beat 1 takes {rows[0]['dur']:.1f}s to say. Cut it to "
                     f"{limit} or fewer, or the hook lands after "
                     "the decision has been made.")
    if rows[0]["concrete"] == 0:
        notes.append("Beat 1 has no number and no name in it. Hooks without something "
                     "checkable are the ones that get scrolled.")

    for r in rows:
        if r["dur"] > MAX_BEAT:
            r["flags"].append(f"{r['dur']:.1f}s on one beat")
    long_beats = [r["n"] for r in rows if r["dur"] > MAX_BEAT]
    if long_beats:
        notes.append(f"Beat(s) {', '.join(map(str, long_beats))} run past {MAX_BEAT:.0f}s. "
                     "Either split the line or change what is on screen inside it. "
                     "A static frame is where people leave.")

    run, start = 0, None
    for r in rows:
        if r["concrete"] == 0:
            run += 1
            start = start if start is not None else r["n"]
            if run == ABSTRACT_RUN:
                notes.append(f"Beats {start}-{r['n']} have nothing concrete in them. "
                             "Put a number, a name or a price in one of them.")
        else:
            run, start = 0, None

    # Does the last line hand you back to the first one?
    first = {w.lower() for w in words(rows[0]["text"]) if w.lower() not in STOPWORDS}
    last = {w.lower() for w in words(rows[-1]["text"]) if w.lower() not in STOPWORDS}
    loop = {pretty(w) for w in first & last}
    # Korean: compare stems, and let a 2+ syllable stem from the hook match
    # inside the last line too, since endings change ("코디" in "코디도").
    last_text = rows[-1]["text"]
    loop |= {s for s in ko_stems(rows[0]["text"])
             if s in ko_stems(last_text) or (len(s) >= 2 and s in last_text)}
    loop = sorted(loop)
    if loop:
        notes.append(f"Loops: the last beat repeats \"{', '.join(loop[:3])}\" from the hook. "
                     "Second watches are free reach.")
    else:
        notes.append("No loop. The last beat shares no word with the hook, so the video "
                     "ends flat. Echoing one word from beat 1 is the cheapest replay you get.")

    if target:
        delta = total - target
        if abs(delta) <= target * 0.1:
            notes.append(f"Length is on target ({total:.1f}s against {target}s).")
        else:
            unit = (f"{int(abs(delta) * sps)} syllables" if korean
                    else f"{int(abs(delta) * wps)} words")
            if delta > 0:
                notes.append(f"{delta:.1f}s over target. Cut about {unit}.")
            else:
                notes.append(f"{-delta:.1f}s under target. Either add {unit} "
                             "or shoot it short. Short is usually right.")

    return {
        "wpm": wpm, "sps": sps, "korean": korean, "target": target,
        "total_seconds": round(total, 2),
        "total_words": sum(r["words"] for r in rows),
        "total_syllables": sum(r["syllables"] for r in rows),
        "beats": rows,
        "notes": notes,
    }


def render(a, out=sys.stdout):
    if a["total_syllables"]:
        size = f"{a['total_syllables']} syllables"
        size += f" + {a['total_words']} words" if a["total_words"] else ""
        rate = f"{a['sps']:g} syl/s" + (f", {a['wpm']:g} wpm" if a["total_words"] else "")
    else:
        size, rate = f"{a['total_words']} words", f"{a['wpm']:g} wpm"
    head = (f"BEAT SHEET  ·  {size}  ·  ~{a['total_seconds']:.1f}s "
            f"at {rate}" + (f"  ·  target {a['target']}s" if a["target"] else ""))
    print("\n" + head, file=out)
    print("=" * max(len(head), 72), file=out)
    for r in a["beats"]:
        label = f"{r['label']:<8}" if r["label"] else " " * 8
        print(f"  {tc(r['start'])}  {r['dur']:4.1f}s  {label}{r['text']}", file=out)
        for f in r["flags"]:
            print(f"  {'':>6}  {'':>5}  {'':<8}^ {f}", file=out)
    print("-" * max(len(head), 72), file=out)
    for n in a["notes"]:
        print(f"  - {n}", file=out)
    print("", file=out)


def main():
    ap = argparse.ArgumentParser(description="Time a Reel script into a beat sheet.")
    ap.add_argument("input", nargs="?", default="-", help="script file, or - for stdin")
    ap.add_argument("--wpm", type=float, default=165, help="speaking rate (default 165)")
    ap.add_argument("--sps", type=float, default=6.0,
                    help="Korean speaking rate in syllables per second (default 6)")
    ap.add_argument("--target", type=float, help="target length in seconds")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    raw = sys.stdin.read() if args.input == "-" else open(args.input, encoding="utf-8").read()
    a = analyse(raw, wpm=args.wpm, target=args.target, sps=args.sps)
    if not a:
        print("empty script", file=sys.stderr)
        sys.exit(2)
    if args.json:
        print(json.dumps(a, indent=2, ensure_ascii=False))
    else:
        render(a)
    sys.exit(0)


if __name__ == "__main__":
    main()
