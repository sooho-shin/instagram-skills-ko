"""
ko.py - Korean support shared by detect.py and humanize.py (local patch).

The original checks count Latin words, so a Hangul draft read as zero words and
every check came back "too short to judge". Korean is measured differently:

  units       eojeol (space-separated chunks), the closest thing to a word
  length      spoken syllables: Hangul syllables, plus two for each Latin word
              or figure, the same rule ig-reel/hookscore.py uses
  sentences   split on . ! ? and line breaks, and after a 요/다/죠/까 ending
              followed by a space, because captions often skip the period
  voice       share of 합쇼체 endings (습니다/입니다) and the density of the
              casual words people actually type (진짜, 근데, ㅋㅋ ...)

Lexicon entries in slop_ko.json are matched as whole words: no Hangul directly
before or after, since particles glue on. "stem": true drops the right edge.
"""

import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
LEX_KO = os.path.join(HERE, "slop_ko.json")

HANGUL_RE = re.compile(r"[가-힣]")
LATIN_WORD_RE = re.compile(r"[A-Za-z]+")
FIGURE_RE = re.compile(r"\d[\d,.]*")
NUMBER_RE = re.compile(r"(?<![A-Za-z])\d[\d,.]*%?")
BRAND_RE = re.compile(r"\b(?:[A-Z][a-z]{2,}|[A-Z]{2,}[a-z]*)\b")
SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+|(?<=[요다죠까])\s+(?=\S)")


def has_hangul(text):
    return bool(HANGUL_RE.search(text))


def is_korean(text):
    """Same rule as ig-reel/beats.py: Hangul outweighs Latin letters."""
    h = len(HANGUL_RE.findall(text))
    return h > 0 and h * 2.5 >= len(re.findall(r"[A-Za-z]", text))


def units(text):
    """Eojeol that carry a letter or a figure. Emoji-only chunks do not count."""
    return [t for t in text.split() if re.search(r"[가-힣A-Za-z0-9]", t)]


def syl_len(text):
    return (len(HANGUL_RE.findall(text))
            + 2 * len(LATIN_WORD_RE.findall(text))
            + 2 * len(FIGURE_RE.findall(text)))


def sentences(text):
    parts = [p.strip() for p in SENT_SPLIT_RE.split(text)]
    return [p for p in parts if syl_len(p) >= 4]


def _final_is_bieup(ch):
    code = ord(ch) - 0xAC00
    return 0 <= code < 11172 and code % 28 == 17


def is_formal(sentence):
    """합쇼체: any ㅂ니다/ㅂ니까 ending (습니다, 입니다, 합니다, 됩니다), or 십시오."""
    s = re.sub(r"[^가-힣]+$", "", sentence)
    if s.endswith("십시오"):
        return True
    return len(s) >= 3 and s[-2:] in ("니다", "니까") and _final_is_bieup(s[-3])


def term_pattern(entry, flags=re.IGNORECASE):
    find = entry["find"]
    if has_hangul(find):
        body = re.escape(find).replace(r"\ ", r"\s*")    # 띄어쓰기는 사람마다 다르다
        # Flag-only entries are never rewritten, so they can match with a
        # particle on the end (여정을, 시너지를). Swapped ones must be whole.
        loose = entry.get("stem") or entry.get("replace", "") is None
        right = "" if loose else r"(?![가-힣])"
        return re.compile(r"(?<![가-힣])" + body + right)
    return re.compile(r"\b" + re.escape(find).replace(r"\ ", r"\s+") + r"\b", flags)


def merge(lex, path=LEX_KO):
    """Fold the Korean lexicon into the English one, in place."""
    if not os.path.exists(path):
        lex.setdefault("colloquial", [])
        return lex
    with open(path, encoding="utf-8") as fh:
        ko = json.load(fh)
    for key in ("words", "phrases", "structures"):
        lex[key] = lex.get(key, []) + [dict(e, lang="ko") for e in ko.get(key, [])]
    lex["colloquial"] = ko.get("colloquial", [])
    return lex


def colloquial_hits(text, words):
    """Casual markers. One-syllable ones (좀, 막, 개) must stand alone,
    or 개 would match 개선 and 제 would match 제품."""
    n = 0
    for w in words:
        if not has_hangul(w):
            n += len(re.findall(re.escape(w), text))
        elif len(w) == 1:
            n += len(re.findall(r"(?<![가-힣])" + re.escape(w) + r"(?![가-힣])", text))
        else:
            n += len(re.findall(r"(?<![가-힣])" + re.escape(w), text))
    return n
