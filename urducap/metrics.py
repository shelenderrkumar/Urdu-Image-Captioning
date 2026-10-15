"""Corpus-level caption metrics on tokenised Urdu: BLEU-4, chrF++ and CIDEr-D.

All metrics are multi-reference and corpus-level. The 2024 notebook averaged
``nltk.sentence_bleu`` over strings, which scores character n-grams; see
``docs/2024-evaluation-audit.md``.
"""

import sacrebleu

from .text import normalize, tokenize


def _tok(text: str) -> str:
    return " ".join(tokenize(text))


def _ref_streams(refs: list[list[str]]) -> list[list[str]]:
    # sacrebleu wants one stream per reference position. Images with fewer references
    # repeat one: a duplicate reference changes neither clipped counts nor the closest
    # reference length, so the score is unchanged.
    width = max(len(r) for r in refs)
    padded = [r + [r[0]] * (width - len(r)) for r in refs]
    return [list(col) for col in zip(*padded, strict=True)]


def bleu4(hyps: list[str], refs: list[list[str]]) -> float:
    streams = _ref_streams([[_tok(r) for r in rs] for rs in refs])
    return sacrebleu.corpus_bleu([_tok(h) for h in hyps], streams, tokenize="none").score


def chrf_pp(hyps: list[str], refs: list[list[str]]) -> float:
    streams = _ref_streams([[normalize(r) for r in rs] for rs in refs])
    return sacrebleu.corpus_chrf([normalize(h) for h in hyps], streams, word_order=2).score


def cider_d(hyps: list[str], refs: list[list[str]]) -> float:
    from pycocoevalcap.cider.cider import Cider

    gts = {i: [_tok(r) for r in rs] for i, rs in enumerate(refs)}
    res = {i: [_tok(h)] for i, h in enumerate(hyps)}
    score, _ = Cider().compute_score(gts, res)
    return 100 * score


def all_metrics(hyps: list[str], refs: list[list[str]]) -> dict[str, float]:
    return {
        "BLEU-4": round(bleu4(hyps, refs), 2),
        "chrF++": round(chrf_pp(hyps, refs), 2),
        "CIDEr-D": round(cider_d(hyps, refs), 2),
        "images": len(hyps),
    }
