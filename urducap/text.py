"""Urdu text normalisation and tokenisation, used for training targets and for metrics.

Urdu is written in an extended Arabic script, and text produced by different keyboards
and translation systems mixes look-alike code points (Arabic yeh and Urdu yeh, Arabic kaf
and keheh, ...). Metrics computed on raw text would count these as different words.
"""

import re
import unicodedata

_CHAR_MAP = str.maketrans(
    {
        "ي": "ی",  # ARABIC YEH -> FARSI/URDU YEH
        "ى": "ی",  # ALEF MAKSURA -> URDU YEH
        "ك": "ک",  # ARABIC KAF -> KEHEH
        "ه": "ہ",  # ARABIC HEH -> HEH GOAL
        "ۀ": "ۂ",  # HEH WITH YEH ABOVE, decomposed
        "\u0640": None,  # TATWEEL (decorative stretching)
        "\u200c": " ",  # ZERO WIDTH NON-JOINER: word boundary inside compounds
        "\u200d": None,
        "\u200f": None,
        "\u200e": None,
        ",": "،",  # Latin comma -> Arabic comma
        "?": "؟",
        ";": "؛",
    }
)
# Short vowels and other diacritics are optional in Urdu and used inconsistently.
_DIACRITICS = re.compile("[ً-ٰٟ]")
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
# A Latin full stop ending a sentence becomes the Urdu full stop (U+06D4).
_FINAL_STOP = re.compile(r"\s*\.\s*$")
_PUNCT = re.compile("([۔،؟؛!\"'()\\[\\]:])")
_SPACE = re.compile(r"\s+")
_URDU_LETTER = re.compile("[؀-ۿ]")
_LATIN_LETTER = re.compile("[A-Za-z]")


def normalize(text: str) -> str:
    """Canonical form of a caption: unified letters, no diacritics, Urdu punctuation."""
    text = unicodedata.normalize("NFC", text).translate(_CHAR_MAP)
    text = _DIACRITICS.sub("", text).translate(_DIGITS)
    text = _FINAL_STOP.sub("۔", text)
    return _SPACE.sub(" ", text).strip()


def tokenize(text: str) -> list[str]:
    """Words and punctuation marks of a normalised caption, for n-gram metrics."""
    return _PUNCT.sub(r" \1 ", normalize(text)).split()


def is_urdu(text: str) -> bool:
    """True when most letters are in the Arabic script (rejects untranslated captions)."""
    urdu = len(_URDU_LETTER.findall(text))
    return urdu > 0 and urdu > len(_LATIN_LETTER.findall(text))
