import json

import pandas as pd

from urducap.data import Item, load_captions, make_splits, select


def test_load_json_and_drop_untranslated(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(
        json.dumps(
            {
                "images": [
                    {"filename": "1.jpg", "sentences": [{"raw": "ایک کتا۔"}, {"raw": "A dog ."}]},
                    {"filename": "2.jpg", "sentences": [{"raw": "دو بلیاں۔"}]},
                ]
            }
        ),
        encoding="utf-8",
    )
    items, stats = load_captions(p)
    assert [i.image for i in items] == ["1.jpg", "2.jpg"]
    assert items[0].captions == ["ایک کتا۔"]
    assert stats["dropped_not_urdu"] == 1 and stats["kept"] == 2


def test_load_flickr_table_with_folder_prefix(tmp_path):
    p = tmp_path / "r.xlsx"
    pd.DataFrame(
        {
            "image_name": ["10/5.jpg", "10/5.jpg"],
            " comment_number": [0, 1],
            "comment": [" ایک کتا ", "ایک بلی"],
        }
    ).to_excel(p, index=False)
    items, _ = load_captions(p)
    assert items == [Item("5.jpg", ["ایک کتا", "ایک بلی"])]


def test_splits_are_image_level_disjoint_and_stable():
    items = [Item(f"{i}.jpg", ["ایک"]) for i in range(100)]
    s = make_splits(items, n_val=10, n_test=10)
    assert len(s["test"]) == len(s["val"]) == 10 and len(s["train"]) == 80
    assert not (set(s["train"]) & set(s["test"])) and not (set(s["val"]) & set(s["test"]))
    assert make_splits(list(reversed(items)), 10, 10) == s


def test_karpathy_split(tmp_path):
    k = tmp_path / "k.json"
    k.write_text(
        json.dumps(
            {"images": [{"filename": "a.jpg", "split": "test"}, {"filename": "b.jpg", "split": "restval"}]}
        )
    )
    s = make_splits([Item("a.jpg"), Item("b.jpg"), Item("c.jpg")], karpathy=k)
    assert s == {"train": ["b.jpg"], "val": [], "test": ["a.jpg"]}


def test_select_with_limit_is_deterministic():
    items = [Item(f"{i}.jpg") for i in range(50)]
    names = [i.image for i in items]
    assert select(items, names, 5) == select(items, names, 5)
