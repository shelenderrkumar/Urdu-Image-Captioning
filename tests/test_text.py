from urducap.text import is_urdu, normalize, tokenize


def test_lookalike_letters_are_unified():
    # Arabic yeh and kaf vs Urdu yeh and keheh: the same word to a reader.
    assert normalize("كتا بيٹھا") == normalize("کتا بیٹھا")


def test_diacritics_and_tatweel_are_removed():
    assert normalize("کـتَا") == "کتا"


def test_latin_full_stop_becomes_urdu_and_is_tokenised():
    assert normalize("ایک کتا .") == "ایک کتا۔"
    assert tokenize("ایک کتا، ایک بلی.") == ["ایک", "کتا", "،", "ایک", "بلی", "۔"]


def test_digits_are_ascii():
    assert tokenize("۲ لڑکے") == ["2", "لڑکے"]


def test_is_urdu_rejects_untranslated_captions():
    assert is_urdu("ایک آدمی سڑک پر چل رہا ہے۔")
    assert not is_urdu("A man walks down the street .")
    assert is_urdu("ایک آدمی pigtails کے ساتھ")
