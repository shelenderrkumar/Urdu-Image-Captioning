"""Command line: ``urducap {audit,split,train,evaluate,caption}``."""

import argparse
import json
import sys
from pathlib import Path

from . import data


def _device():
    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


def cmd_audit(a):
    items, stats = data.load_captions(a.captions)
    counts = [len(i.captions) for i in items]
    words = [len(c.split()) for i in items for c in i.captions]
    report = dict(stats)
    report["captions_per_image"] = round(sum(counts) / max(1, len(counts)), 2)
    report["mean_words"] = round(sum(words) / max(1, len(words)), 2)
    report["duplicate_captions_within_image"] = sum(len(i.captions) - len(set(i.captions)) for i in items)
    print(json.dumps(report, indent=2))


def cmd_split(a):
    items, _ = data.load_captions(a.captions)
    splits = data.make_splits(items, a.val, a.test, a.karpathy)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(splits, indent=1))
    print({k: len(v) for k, v in splits.items()})


def _load_split(a, name, limit=None):
    items, _ = data.load_captions(a.captions)
    splits = json.loads(Path(a.splits).read_text())
    return items, data.select(items, splits[name], limit)


def cmd_train(a):
    from . import models
    from .train import train

    items, train_items = _load_split(a, "train", a.max_train_images)
    _, val_items = _load_split(a, "val", a.max_val_images)
    kwargs = json.loads(a.model_args) if a.model_args else {}
    if a.model == "legacy":
        kwargs["captions"] = [c for i in train_items for c in i.captions]
    if a.model == "vlm":
        kwargs.setdefault("lora", {"r": 16, "alpha": 32})
    model = models.build(a.model, **kwargs).to(_device())
    best = train(
        model,
        train_items,
        val_items,
        a.images,
        a.out,
        a.epochs,
        a.batch_size,
        a.lr,
        a.grad_accum,
        workers=a.workers,
    )
    print(f"best validation CIDEr-D {best:.2f}; model saved in {a.out}")


def _model_from(a):
    from . import models
    from .models.base import load_run

    if a.run:
        return load_run(a.run).to(_device())
    kwargs = json.loads(a.model_args) if a.model_args else {}
    return models.build(a.zero_shot, **kwargs).to(_device())


def cmd_evaluate(a):
    import torch

    from .train import predict, score, write_predictions

    model = _model_from(a)
    _, items = _load_split(a, a.split, a.limit)
    use_amp = model.device.type == "cuda"
    with torch.autocast(model.device.type, dtype=torch.bfloat16, enabled=use_amp):
        records = predict(model, items, a.images, a.batch_size, a.workers, a.beams)
    metrics = score(records)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    write_predictions(records, out / f"{a.split}_predictions.jsonl")
    (out / f"{a.split}_metrics.json").write_text(json.dumps(metrics, indent=2))
    print(json.dumps(metrics, indent=2))


def cmd_caption(a):
    from PIL import Image

    model = _model_from(a).eval()
    images = [Image.open(p).convert("RGB") for p in a.image]
    batch = {k: v.to(model.device) for k, v in model.collate(images).items()}
    for path, text in zip(a.image, model.generate(batch, num_beams=a.beams), strict=True):
        print(f"{path}\t{text}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="urducap", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("audit", help="caption file statistics and quality checks")
    s.add_argument("--captions", required=True)
    s.set_defaults(fn=cmd_audit)

    s = sub.add_parser("split", help="write an image-level train/val/test split")
    s.add_argument("--captions", required=True)
    s.add_argument("--karpathy", help="dataset_flickr30k.json for the standard split")
    s.add_argument("--val", type=int, default=1000)
    s.add_argument("--test", type=int, default=1000)
    s.add_argument("--out", default="data/splits.json")
    s.set_defaults(fn=cmd_split)

    def common(s):
        s.add_argument("--captions", required=True)
        s.add_argument("--images", required=True, help="directory of Flickr30k JPEGs")
        s.add_argument("--splits", default="data/splits.json")
        s.add_argument("--batch-size", type=int, default=32)
        s.add_argument("--workers", type=int, default=2)
        s.add_argument("--model-args", help='JSON, e.g. \'{"base": "Qwen/Qwen3-VL-4B-Instruct"}\'')

    s = sub.add_parser("train", help="fine-tune a model")
    common(s)
    s.add_argument("--model", choices=["legacy", "encdec", "vlm"], required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--epochs", type=int, default=5)
    s.add_argument("--lr", type=float, default=1e-4)
    s.add_argument("--grad-accum", type=int, default=1)
    s.add_argument("--max-train-images", type=int)
    s.add_argument("--max-val-images", type=int, default=500)
    s.set_defaults(fn=cmd_train)

    def which(s):
        g = s.add_mutually_exclusive_group(required=True)
        g.add_argument("--run", help="a directory written by `urducap train`")
        g.add_argument("--zero-shot", choices=["vlm"], help="an untrained model")

    s = sub.add_parser("evaluate", help="caption a split and score it")
    common(s)
    which(s)
    s.add_argument("--split", default="test", choices=["val", "test"])
    s.add_argument("--limit", type=int)
    s.add_argument("--beams", type=int, default=3)
    s.add_argument("--out", required=True)
    s.set_defaults(fn=cmd_evaluate)

    s = sub.add_parser("caption", help="caption image files")
    which(s)
    s.add_argument("image", nargs="+")
    s.add_argument("--beams", type=int, default=3)
    s.add_argument("--model-args")
    s.set_defaults(fn=cmd_caption)

    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
