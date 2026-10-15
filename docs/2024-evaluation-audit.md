# Auditing the 2024 evaluation

The 2024 notebooks (`legacy/`) reported a validation **BLEU of about 0.74**: the mean of
129 per-image scores printed in `training_30k_18_epochs.ipynb`, and 0.7468 in
`training_1k_images.ipynb`. That is far above published Flickr30k results in any
language: BLEU-4 is about 0.19 for Show, Attend and Tell (Xu et al., 2015), the
architecture this model follows, and stays well below 0.5 for modern pre-trained models. Re-reading the code shows two
problems that together explain the number. `scripts/audit_2024_eval.py` reproduces both.

## 1. The validation images were in the training set

The notebook split the 150,000 *(image, caption)* rows with
`train_test_split(..., test_size=0.2, random_state=0)`. Every Flickr30k image has five
captions, so an image whose caption landed in validation almost always had its other
four captions in training.

Replaying that exact split (same row order, same seed):

| | |
|---|---|
| Distinct validation images | 20,142 |
| ... also seen in training | 20,132 (**99.95%**) |
| Images the evaluation loop scored | 6,000 |
| ... seen in training | 5,989 (**99.8%**) |

The model was mostly scored on images it had memorised. The example printed in the
notebook (BLEU 0.74) is a near-copy of one of that image's own reference captions, which
is the kind of output memorisation produces.

**Fix:** split by image. `urducap split` uses the standard Karpathy split (29,000 / 1,014 /
1,000 images) when `dataset_flickr30k.json` is available, or a stable hash of the file
name otherwise. No caption of a test image is ever used for training.

## 2. BLEU counted characters, not words

```python
sentence_bleu(cleaned, predicted)  # cleaned: list[str], predicted: str
```

NLTK expects token lists. Given strings, it iterates over them character by character,
so it scores character n-grams. Two unrelated Urdu sentences share many letters and
short letter sequences, so they get a high score.

As a calibration, we scored each Flickr30k caption against the image's other four
human captions, over 2,000 images. The repository's `results.xlsx` held mostly the
original English captions: only 498 of its 158,915 rows had been translated.

| Metric | Human caption vs other humans |
|---|---|
| Character-level BLEU (the notebook's computation) | 0.568 |
| Word-level BLEU-4 | 0.136 |

Character-level BLEU inflates scores about 4×. The notebook's 0.74 is higher than what
*humans* score against each other, which points back to problem 1: memorisation.

**Fix:** `urducap.metrics` computes corpus-level BLEU-4 with sacreBLEU on normalised,
tokenised Urdu (punctuation split off, look-alike Arabic and Urdu letters unified). It
also reports chrF++ (robust to Urdu's rich morphology) and CIDEr-D (the standard
captioning metric).

## 3. Smaller issues, also fixed

- **Random decoding at test time.** The notebook used `tf.random.categorical`, so every
  evaluation gave different captions. Evaluation now uses greedy or beam search.
- **`<end>` was part of the predicted string.** It was scored as if it were a word.
- **Untranslated captions.** Rows still in English were not filtered out. `urducap`
  drops any caption that is not mainly in Arabic script, and reports how many it dropped.

## Takeaway

The 2024 architecture was reasonable for its time. Its numbers were not. Version 2
re-trains the same architecture under the corrected protocol, so it serves as an honest
baseline for the modern models.
