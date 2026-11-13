#!/usr/bin/env python3
"""
hookscore.py - score the first line of a Reel on the five things strong hooks
have in common, and rank a batch of them against each other.

What this is:  five local heuristics, computed on your machine from the text
alone. They measure properties that hooks which hold attention tend to share -
a length you can say in under three seconds, a concrete marker, something at stake,
the payload at the front rather than the back, and a viewer to aim it at.

What this is NOT:  a view predictor. It was tested against 74 real short-form
hooks, transcribed from the first three seconds of the top eight and bottom
eight performers on five channels. Separating a real hook from a deliberately
bad one it does well: AUC 0.83, and 9 of 10 written-to-be-bad hooks scored
below the real median. Separating a good creator's hits from that same
creator's misses it barely does at all: AUC 0.56, where 0.50 is a coin flip.

So use it for what it measured well. It catches greetings, preambles, hooks
with nothing concrete in them and hooks that take five seconds to say. It will
not tell you which of two decent hooks will travel, and nothing that reads text
can, because that is decided by your face, your edit, your audio and who
Instagram shows it to. Trust the retention graph over this script.

Each check returns 0 to 100. Higher is better.

Usage
  python3 hookscore.py hooks.txt              # one hook per line, ranked
  python3 hookscore.py --hook "I lost $18,000 on one missing contract."
  pbpaste | python3 hookscore.py -
  python3 hookscore.py hooks.txt --json
"""

import argparse
import json
import re
import statistics
import sys

WORD_RE = re.compile(r"[A-Za-z0-9$%'’-]+")
NUMBER_RE = re.compile(
    r"\$\s?\d[\d,]*(?:\.\d+)?"                       # money, whole
    r"|\b\d[\d,]*(?:\.\d+)?\s?"                      # a figure, with or
    r"(?:%|k\b|x\b|hrs?\b|hours?\b|mins?\b|minutes?\b"  # without a unit
    r"|days?\b|weeks?\b|months?\b|years?\b)?",
    re.IGNORECASE)
PROPER_RE = re.compile(r"(?<!^)\b[A-Z][a-z]{2,}\b")
HASHTAG_RE = re.compile(r"(?:^|\s)#\w+")
EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF☀-➿]")

# Spoken hooks say their numbers out loud. "Zero dollars" and "twenty grand"
# are as concrete as "$0" and "$20,000", and counting only digits missed them.
# "one" and "first" are deliberately absent: they are filler far more often
# than they are a quantity.
SPOKEN_NUMBERS = {
    "zero", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "eleven", "twelve", "fifteen", "twenty", "thirty", "forty", "fifty",
    "sixty", "seventy", "eighty", "ninety", "hundred", "thousand", "million",
    "billion", "dozen", "half", "twice", "triple",
}
MONEY_WORDS = {
    "dollars", "dollar", "bucks", "grand", "percent", "cents",
    "millionaire", "billionaire", "revenue", "profit", "salary", "rent",
}

# Words that put something on the line. A hook with none of these is a
# statement; a hook with one is a reason to keep watching.
STAKES = {
    "stop", "never", "wrong", "mistake", "mistakes", "lost", "lose", "losing",
    "cost", "costs", "broke", "broken", "failed", "failure", "fail", "nobody",
    "no", "not", "don't", "dont", "doesn't", "didn't", "can't", "won't",
    "quit", "quitting", "fired", "deleted", "delete", "killed", "kills", "kill",
    "replaced", "replaces", "cut", "beat", "free", "paid", "charged", "hired",
    "saved", "first",
    "banned", "illegal", "worst", "hate", "hated", "wasted", "waste", "scam",
    "lie", "lied", "lying", "truth", "secret", "hidden", "stole", "stolen",
    "before", "until", "instead", "but", "except", "unless", "problem",
    "risk", "danger", "warning", "regret", "wish", "should", "shouldn't",
    "still", "already", "only", "without", "versus", "vs", "actually",
}

# Openers that spend the first second saying nothing.
WEAK_OPENERS = [
    "so", "ok", "okay", "hey", "hi", "hello", "guys", "yo", "alright",
    "welcome", "today", "basically", "honestly", "look", "listen", "um",
    "just", "let", "lets", "let's", "i wanted", "i want", "one of",
    "have you", "did you", "do you", "are you", "in this", "in today",
    "the thing", "a lot", "there is", "there are", "this is", "it is",
    "as a", "when it", "if you've", "you know",
]

# Imperatives that earn the front position.
IMPERATIVES = {
    "stop", "steal", "copy", "delete", "try", "watch", "read", "save",
    "use", "build", "make", "write", "send", "take", "start", "quit",
    "never", "always", "don't", "dont", "do", "put", "run", "check",
}

# ---- Korean -------------------------------------------------------------
# The checks above count Latin words, so a Hangul hook used to read as zero
# words. Korean lines are scored on spoken syllables instead, and the word
# lists are matched as stems because particles and endings attach to them.
HANGUL_RE = re.compile(r"[가-힣]")
KO_SYLLABLES_PER_SEC = 6.0
KO_DIGIT_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
KO_NUMBER_RE = re.compile(
    r"(?:두|세|네|다섯|여섯|일곱|여덟|아홉|열|스무|서른|마흔|쉰)\s"
    r"(?:초|분|시간|일|주|달|개월|년|번|개|명|배|벌|켤레|가지|살)"
    r"|(?:백|천|만|억)\s?원|절반|두\s?배|반값")
KO_MONEY_RE = re.compile(r"\d\s?원|매출|월급|수익|월세|연봉|가격")
KO_STAKES = [
    ("그만", r"그만"), ("절대", r"절대"), ("틀림", r"틀렸|틀린|틀려"),
    ("실수", r"실수"), ("잃음", r"잃"), ("날림", r"날렸|날린|날려"),
    ("망함", r"망했|망친|망쳐|망함"), ("손해", r"손해"), ("비용", r"비용"),
    ("실패", r"실패"), ("아무도", r"아무도"), ("부정", r"(?:^|\s)(?:안|못)\s|않|없"),
    ("버림", r"버렸|버린|버려|버리"), ("낭비", r"낭비"), ("무료", r"공짜|무료"),
    ("끝", r"끝"), ("대신", r"대신"), ("반전", r"하지만|근데|그런데"),
    ("진실", r"사실은|진실"), ("비밀", r"비밀|숨겨"), ("문제", r"문제"),
    ("후회", r"후회"), ("이미", r"이미|아직"), ("하나만", r"오직|딱\s?하나|하나로|만으로"),
    ("처음", r"처음|첫"), ("삭제", r"삭제|지웠"), ("교체", r"바꿨|바뀌|대체"),
    ("줄임", r"줄였|줄인|줄여"), ("최악", r"최악"), ("싫음", r"싫"), ("비교", r"(?i)\bvs\b"),
    ("전후", r"이제는|이젠|전에는|예전엔|원래는"),
]
KO_STAKE_RES = [(name, re.compile(p)) for name, p in KO_STAKES]
KO_WEAK_OPENER_RE = re.compile(
    r"^\s*(?:자[,\s]|그래서|음+|어+[,\s]|일단|오늘은|오늘\s|이번에|혹시|여러분"
    r"|안녕|제가\s오늘|그냥|솔직히|아\s)")
KO_VIEWER_RE = re.compile(r"당신|너는|너도|니가|네가|여러분")
KO_ASK_RE = re.compile(r"세요|마세요|하지\s?마|해\s?봐|나요\?|죠\?|\?\s*$")
KO_FIRST_PERSON_RE = re.compile(r"(?:^|\s)(?:저는|저도|제가|제\s|내가|나는|나도|내\s|우리|저희)")


def hangul_count(text):
    return len(HANGUL_RE.findall(text))


def is_korean(text):
    h = hangul_count(text)
    return h > 0 and h * 2.5 >= len(re.findall(r"[A-Za-z]", text))


def ko_syllables(text):
    """Hangul syllables, plus about two for each Latin word or figure."""
    return hangul_count(text) + 2 * len(WORD_RE.findall(text))


def ko_has_payload(token):
    return bool(KO_DIGIT_RE.search(token) or KO_NUMBER_RE.search(token)
                or KO_MONEY_RE.search(token)
                or any(r.search(" " + token + " ") for _, r in KO_STAKE_RES)
                or PROPER_RE.search(" " + token))


DEALBREAKERS = [
    (re.compile(r"^\s*(?:잠깐만?요?[!,.\s]|스크롤\s?멈|넘기지\s?마)"),
     "Opens with \"stop scrolling\" (잠깐만요/넘기지 마세요). Asking for attention proves you have not earned it."),
    (re.compile(r"이번\s?영상|오늘\s?영상|이\s?영상에서|소개해\s?드릴|소개할게|소개합니다|알려\s?드릴|보여\s?드릴"),
     "Video preamble (이번 영상/소개해 드릴게요). Delete it and open on the payoff."),
    (re.compile(r"^\s*(?:안녕|여러분\s?안녕|하이\s|헬로)"),
     "Greeting (안녕하세요). Nobody came to the feed to be greeted."),
    (re.compile(r"(?i)^\s*(?:stop scrolling|don'?t scroll)"),
     "Opens with \"stop scrolling\". Asking for attention proves you have not earned it."),
    (re.compile(r"(?i)\b(?:in (?:this|today'?s) (?:video|reel)|i'?m going to show you|i'?ll show you how)\b"),
     "Video preamble. Delete it and open on the payoff."),
    (re.compile(r"(?i)^\s*(?:hey |hi |what'?s up |welcome )"),
     "Greeting. Nobody came to the feed to be greeted."),
    (HASHTAG_RE,
     "Hashtag in the hook. Hashtags belong at the bottom of the caption, if anywhere."),
    (EMOJI_RE,
     "Emoji in the hook. On-screen text at hook size has room for words or for an emoji, not both."),
]


def clamp(n):
    return max(0.0, min(100.0, n))


def words(text):
    # "$18,000" is one word when it is spoken, so it is one word here too.
    return WORD_RE.findall(re.sub(r"(?<=\d),(?=\d)", "", text))


def check_length(text):
    """A hook has to land before the thumb moves. Roughly two seconds."""
    if is_korean(text):
        syl = ko_syllables(text)
        secs = syl / KO_SYLLABLES_PER_SEC
        chars = len(re.sub(r"\s", "", text))
        if 8 <= syl <= 18:
            score = 100.0
        elif syl < 8:
            score = clamp(100 - (8 - syl) * 12)
        else:
            score = clamp(100 - (syl - 18) * 7)
        if chars > 24:                   # two lines of big Hangul on screen
            score -= 12
        return clamp(score), (f"{syl} syllables, {chars} chars, ~{secs:.1f}s spoken "
                              "(want 8-18 syllables)")
    w = words(text)
    n = len(w)
    secs = n / 2.75                      # ~165 words per minute, spoken
    chars = len(text.strip())
    if 5 <= n <= 12:
        score = 100.0
    elif n < 5:
        score = clamp(100 - (5 - n) * 20)
    else:
        score = clamp(100 - (n - 12) * 11)
    if chars > 60:                       # two lines of big on-screen text
        score -= 12
    return clamp(score), f"{n} words, {chars} chars, ~{secs:.1f}s spoken (want 5-12 words)"


def check_specificity(text):
    """One concrete thing beats three abstract ones."""
    propers = set(PROPER_RE.findall(text))
    if is_korean(text):
        nums = KO_DIGIT_RE.findall(text)
        spoken = KO_NUMBER_RE.findall(text) + KO_MONEY_RE.findall(text)
    else:
        nums = [n.strip() for n in NUMBER_RE.findall(text) if n.strip()]
        low = [w.lower().strip("'’") for w in words(text)]
        spoken = [w for w in low if w in SPOKEN_NUMBERS or w in MONEY_WORDS]
    hits = len(nums) + len(propers) + len(spoken)
    score = 15.0 if hits == 0 else clamp(45 + hits * 30)
    found = ", ".join(nums[:2] + sorted(propers)[:2] + spoken[:2])
    return score, (f"{hits} concrete marker(s)" + (f": {found}" if found else
                   " - no number, no name, nothing checkable"))


def check_stakes(text):
    """Tension, cost, negation. Something the viewer might lose."""
    if is_korean(text):
        padded = " " + text + " "
        markers = sorted({name for name, r in KO_STAKE_RES if r.search(padded)})
    else:
        w = [x.lower().strip("'’") for x in words(text)]
        markers = sorted({x for x in w if x in STAKES})
    if re.search(r"\$\s?\d", text):
        markers.append("a price")
    n = len(markers)
    score = {0: 20.0, 1: 70.0}.get(n, 100.0)
    detail = f"{n} tension marker(s)" + (f": {', '.join(markers[:4])}" if markers else
                                         " - nothing is at stake in this line")
    return clamp(score), detail


def check_frontload(text):
    """The interesting word cannot be in position nine."""
    if is_korean(text):
        # Korean packs a word plus its particle into one spaced unit (eojeol),
        # so positions are counted in eojeol and the thresholds are tighter.
        toks = text.split()
        if not toks:
            return 0.0, "empty"
        m = KO_WEAK_OPENER_RE.match(text)
        penalty = 30 if m else 0
        payload = next((i for i, t in enumerate(toks) if ko_has_payload(t)), None)
        if payload is None:
            base, where = 30.0, "no payload word anywhere in the line"
        elif payload <= 1:
            base, where = 100.0, f"payload at eojeol {payload + 1}"
        elif payload <= 3:
            base, where = 70.0, f"payload at eojeol {payload + 1}, could move forward"
        else:
            base, where = 40.0, f"payload at eojeol {payload + 1}, too late"
        detail = where + (f"; weak opener \"{m.group(0).strip()}\"" if m else "")
        return clamp(base - penalty), detail
    w = words(text)
    if not w:
        return 0.0, "empty"
    low = [x.lower().strip("'’") for x in w]
    opener = " ".join(low[:2])
    penalty = 0
    hit_opener = None
    for weak in WEAK_OPENERS:
        if opener.startswith(weak) or low[0] == weak:
            penalty, hit_opener = 30, weak
            break
    payload = None
    for i, token in enumerate(low):
        if (token in STAKES or token in SPOKEN_NUMBERS or token in MONEY_WORDS
                or NUMBER_RE.match(w[i]) or (i and PROPER_RE.match(w[i]))):
            payload = i
            break
    if payload is None:
        base = 30.0
        where = "no payload word anywhere in the line"
    elif payload <= 3:
        base = 100.0
        where = f"payload at word {payload + 1}"
    elif payload <= 6:
        base = 70.0
        where = f"payload at word {payload + 1}, could move forward"
    else:
        base = 40.0
        where = f"payload at word {payload + 1}, too late"
    detail = where + (f"; weak opener \"{hit_opener}\"" if hit_opener else "")
    return clamp(base - penalty), detail


def check_address(text):
    """Aimed at one viewer, or floating in the air."""
    if is_korean(text):
        # Korean drops "you" most of the time; the ending carries it instead.
        if KO_VIEWER_RE.search(text):
            return 100.0, "speaks to the viewer"
        if KO_ASK_RE.search(text):
            return 90.0, "imperative or question ending (aimed at the viewer)"
        if KO_FIRST_PERSON_RE.search(" " + text):
            return 70.0, "first person, no viewer named"
        # Past tense (a syllable closed by ㅆ: 었/았/렸/웠/했...) before a plain
        # ending is almost always the speaker's own story in a hook.
        for m in re.finditer(r"([가-힣])(?:어요|어|다|습니다|죠|고요)", text):
            if (ord(m.group(1)) - 0xAC00) % 28 == 20:
                return 70.0, "first person implied by the ending, no viewer named"
        return 35.0, "third person, nobody in the room"
    low = text.lower()
    w = [x.lower().strip("'’") for x in words(text)]
    if re.search(r"\b(you|your|you're|youre|yourself)\b", low):
        return 100.0, "speaks to the viewer"
    if w and w[0] in IMPERATIVES:
        return 90.0, f"imperative opener (\"{w[0]}\")"
    if re.search(r"\b(i|my|me|we|our)\b", low):
        return 70.0, "first person, no viewer named"
    return 35.0, "third person, nobody in the room"


CHECKS = ["LENGTH", "SPECIFICITY", "STAKES", "FRONTLOAD", "ADDRESS"]


def run(text):
    results = {
        "LENGTH": check_length(text),
        "SPECIFICITY": check_specificity(text),
        "STAKES": check_stakes(text),
        "FRONTLOAD": check_frontload(text),
        "ADDRESS": check_address(text),
    }
    flags = [msg for pattern, msg in DEALBREAKERS if pattern.search(text)]
    scores = [results[c][0] for c in CHECKS]
    # The weakest property caps the hook, same logic as detect.py: one bad
    # property is enough for the thumb to keep moving.
    overall = statistics.mean(scores) * 0.6 + min(scores) * 0.4 - len(flags) * 15
    overall = clamp(overall)
    verdict = "STRONG" if overall >= 70 and min(scores) >= 55 and not flags else (
        "OK" if overall >= 50 else "WEAK")
    return results, overall, verdict, flags


def bar(score, width=24):
    filled = round(score / 100 * width)
    return "#" * filled + "." * (width - filled)


def render_one(text, results, overall, verdict, flags, out=sys.stdout):
    print("\nHOOK SCORE", file=out)
    print("=" * 62, file=out)
    print(f"  \"{text.strip()}\"\n", file=out)
    for name in CHECKS:
        score, detail = results[name]
        print(f"  {name:<13} {bar(score)} {score:5.1f}", file=out)
        print(f"  {'':<13} {detail}", file=out)
    print("-" * 62, file=out)
    print(f"  {'HOOK SCORE':<13} {bar(overall)} {overall:5.1f}   {verdict}", file=out)
    for f in flags:
        print(f"\n  DEALBREAKER  {f}", file=out)
    if verdict != "STRONG":
        weakest = min(CHECKS, key=lambda c: results[c][0])
        print(f"\n  Weakest property: {weakest}. Fix that one and re-run.", file=out)
    print("", file=out)


def render_table(rows, out=sys.stdout):
    print("\nHOOK RANKING\n" + "=" * 78, file=out)
    for i, r in enumerate(rows, 1):
        mark = "->" if i == 1 else "  "
        hook = r["hook"] if len(r["hook"]) <= 62 else r["hook"][:59] + "..."
        print(f"{mark} {r['score']:5.1f} {r['verdict']:<7} {hook}", file=out)
        print(f"        weakest: {r['weakest']} ({r['checks'][r['weakest']]['score']:.0f})", file=out)
        for f in r["flags"]:
            print(f"        dealbreaker: {f}", file=out)
    print("\nShoot the top one. If the top one is under 50, none of these are the hook.\n",
          file=out)


def main():
    ap = argparse.ArgumentParser(description="Score a Reel hook on five properties.")
    ap.add_argument("input", nargs="?", default="-", help="file with one hook per line, or -")
    ap.add_argument("--hook", help="score a single hook given on the command line")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.hook:
        lines = [args.hook]
    else:
        raw = sys.stdin.read() if args.input == "-" else open(args.input, encoding="utf-8").read()
        lines = [l.strip() for l in raw.splitlines() if l.strip()]
    if not lines:
        print("nothing to score", file=sys.stderr)
        sys.exit(2)

    payload = []
    for line in lines:
        results, overall, verdict, flags = run(line)
        payload.append({
            "hook": line,
            "checks": {k: {"score": round(v[0], 1), "detail": v[1]} for k, v in results.items()},
            "weakest": min(CHECKS, key=lambda c: results[c][0]),
            "flags": flags,
            "score": round(overall, 1),
            "verdict": verdict,
        })

    if args.json:
        print(json.dumps(payload if len(payload) > 1 else payload[0], indent=2, ensure_ascii=False))
        return

    if len(payload) == 1:
        results, overall, verdict, flags = run(lines[0])
        render_one(lines[0], results, overall, verdict, flags)
    else:
        render_table(sorted(payload, key=lambda r: -r["score"]))

    sys.exit(0 if max(p["score"] for p in payload) >= 70 else 1)


if __name__ == "__main__":
    main()
