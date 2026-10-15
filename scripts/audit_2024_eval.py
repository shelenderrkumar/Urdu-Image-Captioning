"""Re-examine how the 2024 notebook (legacy/DL_Project-18 epochs.ipynb) measured its BLEU.

It replays the notebook's data order and its train/validation split exactly, then reports:

1. Leakage: the split was made over (image, caption) rows, not over images, so most
   validation images also appear in training with their other captions.
2. Character-level BLEU: ``nltk.sentence_bleu(refs, hyp)`` was given strings, not token
   lists, so it counted character n-grams. We compare it to word-level BLEU on human
   references (each Flickr30k caption scored against the image's other four captions).

Usage: python scripts/audit_2024_eval.py path/to/results.csv-or-xlsx
(Flickr30k's ``results.csv`` from Kaggle, or the repository's former ``results.xlsx``.)
"""

import sys

import numpy as np
import pandas as pd
from nltk.translate.bleu_score import SmoothingFunction, sentence_bleu
from sklearn.model_selection import train_test_split


def load(path):
    if path.endswith(".xlsx"):
        df = pd.read_excel(path)
    else:
        df = pd.read_csv(path, sep="|")
    df.columns = [c.strip() for c in df.columns]
    df["comment"] = df["comment"].astype(str).str.strip()
    return df


def replay_split(df):
    # JSON_Captions.ipynb grouped by image_name (sorted), the training notebook took the
    # first 30,000 images with 5 captions each, in that order, and split the rows.
    groups = list(df.groupby("image_name"))[:30000]
    names = [name for name, g in groups for _ in range(5)]
    rows = np.arange(len(names))
    train_rows, val_rows = train_test_split(rows, test_size=0.2, random_state=0)
    train_imgs = {names[i] for i in train_rows}
    val_imgs = [names[i] for i in val_rows]
    evaluated = val_imgs[::5]  # the notebook's loop: range(0, len(img_name_val), 5)
    leaked = sum(n in train_imgs for n in evaluated)
    return len(set(val_imgs)), len(evaluated), leaked, sum(n in train_imgs for n in set(val_imgs))


def bleu_gap(df, limit=2000):
    smooth = SmoothingFunction().method1
    char, word = [], []
    for _, g in list(df.groupby("image_name"))[:limit]:
        caps = g["comment"].tolist()
        if len(caps) < 5:
            continue
        hyp, refs = caps[0], caps[1:]
        char.append(sentence_bleu(refs, hyp))  # what the notebook did
        word.append(sentence_bleu([r.split() for r in refs], hyp.split(), smoothing_function=smooth))
    return np.mean(char), np.mean(word), len(char)


def main(path):
    df = load(path)
    n_val, n_eval, leaked, leaked_all = replay_split(df)
    print(f"validation images: {n_val}, also in training: {leaked_all} ({leaked_all / n_val:.1%})")
    print(f"images scored by the notebook: {n_eval}, seen in training: {leaked} ({leaked / n_eval:.1%})")
    char, word, n = bleu_gap(df)
    print(f"human caption vs the other 4 human captions, {n} images:")
    print(f"  BLEU as the notebook computed it (characters): {char:.3f}")
    print(f"  word-level BLEU-4:                             {word:.3f}")


if __name__ == "__main__":
    main(sys.argv[1])
