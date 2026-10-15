"""Caption files, image-level splits and PyTorch datasets."""

import hashlib
import json
import random
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .text import is_urdu, normalize


@dataclass
class Item:
    image: str  # file name, e.g. "1000092795.jpg"
    captions: list[str] = field(default_factory=list)


def _basename(name: str) -> str:
    return Path(str(name).strip()).name


def load_captions(path: str | Path) -> tuple[list[Item], Counter]:
    """Read captions from a Karpathy-style JSON file or a CSV/XLSX table.

    JSON: ``{"images": [{"filename": ..., "sentences": [{"raw": ...}, ...]}, ...]}``.
    Tables: columns ``image_name`` and ``comment`` (Flickr30k's ``results.csv`` layout,
    ``|``-separated). Captions are normalised; captions that are not in Urdu script are
    dropped and counted, so an untranslated row can never become a training target.
    """
    path = Path(path)
    stats: Counter = Counter()
    rows: dict[str, list[str]] = {}
    if path.suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        pairs = ((img["filename"], s["raw"]) for img in data["images"] for s in img["sentences"])
    else:
        import pandas as pd

        if path.suffix in (".xlsx", ".xls"):
            df = pd.read_excel(path)
        else:
            df = pd.read_csv(path, sep="|" if path.suffix == ".csv" else "\t")
        df.columns = [str(c).strip() for c in df.columns]
        pairs = zip(df["image_name"], df["comment"], strict=True)
    for image, caption in pairs:
        stats["captions"] += 1
        caption = normalize(str(caption))
        if not is_urdu(caption):
            stats["dropped_not_urdu"] += 1
            continue
        rows.setdefault(_basename(image), []).append(caption)
    items = [Item(image, caps) for image, caps in sorted(rows.items())]
    stats["images"] = len(items)
    stats["kept"] = sum(len(i.captions) for i in items)
    return items, stats


def make_splits(
    items: list[Item], n_val: int = 1000, n_test: int = 1000, karpathy: str | Path | None = None
) -> dict[str, list[str]]:
    """Split by image, never by caption, so no test image is ever seen in training.

    With ``karpathy`` (``dataset_flickr30k.json`` from Karpathy & Fei-Fei, 2015) the
    standard 29k/1k/1k split is used, so results are comparable with the literature.
    Otherwise images are ordered by a hash of their name, which is stable across
    machines and independent of file order.
    """
    names = [i.image for i in items]
    if karpathy:
        data = json.loads(Path(karpathy).read_text(encoding="utf-8"))
        split_of = {img["filename"]: img["split"] for img in data["images"]}
        out = {"train": [], "val": [], "test": []}
        for name in names:
            split = split_of.get(name)
            if split in ("val", "test"):
                out[split].append(name)
            elif split in ("train", "restval"):
                out["train"].append(name)
        return out
    ordered = sorted(names, key=lambda n: hashlib.sha1(n.encode()).hexdigest())
    return {
        "test": sorted(ordered[:n_test]),
        "val": sorted(ordered[n_test : n_test + n_val]),
        "train": sorted(ordered[n_test + n_val :]),
    }


def select(items: list[Item], names: list[str], limit: int | None = None) -> list[Item]:
    wanted = set(names)
    chosen = [i for i in items if i.image in wanted]
    if limit:
        chosen = random.Random(0).sample(chosen, min(limit, len(chosen)))
    return chosen


class PairDataset:
    """One example per (image, caption): the training set."""

    def __init__(self, items: list[Item], image_dir: str | Path):
        self.pairs = [(i.image, c) for i in items for c in i.captions]
        self.image_dir = Path(image_dir)

    def __len__(self):
        return len(self.pairs)

    def __getitem__(self, idx):
        from PIL import Image

        name, caption = self.pairs[idx]
        return Image.open(self.image_dir / name).convert("RGB"), caption


class ImageDataset:
    """One example per image with all its reference captions: validation and test."""

    def __init__(self, items: list[Item], image_dir: str | Path):
        self.items = items
        self.image_dir = Path(image_dir)

    def __len__(self):
        return len(self.items)

    def __getitem__(self, idx):
        from PIL import Image

        item = self.items[idx]
        return Image.open(self.image_dir / item.image).convert("RGB"), item
