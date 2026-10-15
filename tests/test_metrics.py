import pytest
from nltk.translate.bleu_score import sentence_bleu

from urducap.metrics import all_metrics, bleu4, chrf_pp, cider_d

REFS = [
    ["ایک کتا گھاس پر دوڑ رہا ہے۔", "ایک بھورا کتا باہر کھیل رہا ہے۔"],
    ["دو بچے ساحل پر کھیل رہے ہیں۔", "بچے ریت میں کھیل رہے ہیں۔"],
]


def test_perfect_predictions_score_maximum_bleu():
    assert bleu4([r[0] for r in REFS], REFS) == pytest.approx(100.0)


def test_unrelated_predictions_score_low():
    bad = ["سرخ گاڑی سڑک پر کھڑی ہے۔", "ایک عورت کتاب پڑھ رہی ہے۔"]
    assert bleu4(bad, REFS) < 15
    assert cider_d(bad, REFS) < cider_d([r[0] for r in REFS], REFS)
    assert chrf_pp(bad, REFS) < chrf_pp([r[0] for r in REFS], REFS)


def test_normalisation_makes_lookalike_letters_match():
    arabic_letters = "ايک كتا گھاس پر دوڑ رہا ہے۔"
    assert bleu4([arabic_letters, REFS[1][0]], REFS) == pytest.approx(100.0)


def test_unequal_reference_counts_match_padded():
    refs = [REFS[0][:1], REFS[1]]
    hyps = ["ایک کتا دوڑ رہا ہے۔", "بچے کھیل رہے ہیں۔"]
    padded = [REFS[0][:1] * 2, REFS[1]]
    assert bleu4(hyps, refs) == pytest.approx(bleu4(hyps, padded))


def test_all_metrics_keys():
    m = all_metrics([r[0] for r in REFS], REFS)
    assert set(m) == {"BLEU-4", "chrF++", "CIDEr-D", "images"}


def test_the_2024_string_bleu_counted_characters():
    # sentence_bleu on strings iterates characters, so two different sentences sharing
    # letters get a high score. This is what the 2024 notebook reported.
    hyp, refs = "ایک بلی میز پر بیٹھی ہے۔", ["ایک کتا گھاس پر دوڑ رہا ہے۔"]
    char_level = sentence_bleu(refs, hyp)
    word_level = bleu4([hyp], [refs])
    assert 100 * char_level > word_level + 10
