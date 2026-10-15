"""One training and evaluation loop for every model kind."""

import json
import math
import time
from pathlib import Path

import torch
from torch.utils.data import DataLoader

from .data import ImageDataset, Item, PairDataset
from .metrics import all_metrics


def _loader(dataset, model, batch_size, train, workers):
    if train:
        collate = lambda ex: model.collate([e[0] for e in ex], [e[1] for e in ex])  # noqa: E731
    else:
        collate = lambda ex: (model.collate([e[0] for e in ex]), [e[1] for e in ex])  # noqa: E731
    return DataLoader(dataset, batch_size, shuffle=train, num_workers=workers, collate_fn=collate)


def _to(batch: dict, device):
    return {k: v.to(device) if torch.is_tensor(v) else v for k, v in batch.items()}


def predict(model, items: list[Item], image_dir, batch_size=16, workers=2, num_beams=3, progress=True):
    """Caption every image; returns one record per image with its references."""
    model.eval()
    out = []
    loader = _loader(ImageDataset(items, image_dir), model, batch_size, False, workers)
    for n, (batch, batch_items) in enumerate(loader, 1):
        hyps = model.generate(_to(batch, model.device), num_beams=num_beams)
        out += [
            {"image": it.image, "prediction": h, "references": it.captions}
            for it, h in zip(batch_items, hyps, strict=True)
        ]
        if progress and n % 10 == 0:
            print(f"  captioned {len(out)}/{len(items)}", flush=True)
    return out


def score(records: list[dict]) -> dict:
    return all_metrics([r["prediction"] for r in records], [r["references"] for r in records])


def write_predictions(records, path):
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def train(
    model,
    train_items: list[Item],
    val_items: list[Item],
    image_dir,
    out_dir,
    epochs=5,
    batch_size=32,
    lr=1e-4,
    grad_accum=1,
    warmup=0.05,
    workers=2,
    log_every=50,
):
    """AdamW with linear warm-up and cosine decay. Keeps the checkpoint with the best
    validation CIDEr-D and writes a JSON-lines training log."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    device = model.device
    params = [p for p in model.parameters() if p.requires_grad]
    print(f"trainable parameters: {sum(p.numel() for p in params) / 1e6:.1f} M", flush=True)
    opt = torch.optim.AdamW(params, lr=lr, weight_decay=0.01)
    loader = _loader(PairDataset(train_items, image_dir), model, batch_size, True, workers)
    total = epochs * math.ceil(len(loader) / grad_accum)
    warm = max(1, int(warmup * total))
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: min(1.0, (s + 1) / warm) * 0.5 * (1 + math.cos(math.pi * min(1.0, s / total)))
    )
    use_amp = device.type == "cuda"
    amp_dtype = torch.bfloat16 if use_amp and torch.cuda.is_bf16_supported() else torch.float16
    scaler = torch.amp.GradScaler(enabled=use_amp and amp_dtype == torch.float16)
    log = open(out_dir / "train_log.jsonl", "a", encoding="utf-8")
    best, step = -1.0, 0
    for epoch in range(1, epochs + 1):
        model.train()
        t0, running = time.time(), 0.0
        for i, batch in enumerate(loader, 1):
            with torch.autocast(device.type, dtype=amp_dtype, enabled=use_amp):
                loss = model.loss(_to(batch, device)) / grad_accum
            scaler.scale(loss).backward()
            running += loss.item() * grad_accum
            if i % grad_accum == 0 or i == len(loader):
                scaler.unscale_(opt)
                torch.nn.utils.clip_grad_norm_(params, 1.0)
                scaler.step(opt)
                scaler.update()
                opt.zero_grad(set_to_none=True)
                sched.step()
                step += 1
            if i % log_every == 0:
                rec = {
                    "epoch": epoch,
                    "batch": i,
                    "loss": round(running / log_every, 4),
                    "lr": sched.get_last_lr()[0],
                }
                print(json.dumps(rec), flush=True)
                log.write(json.dumps(rec) + "\n")
                running = 0.0
        with torch.autocast(device.type, dtype=amp_dtype, enabled=use_amp):
            records = predict(model, val_items, image_dir, batch_size, workers, progress=False)
        metrics = score(records)
        rec = {"epoch": epoch, "val": metrics, "minutes": round((time.time() - t0) / 60, 1)}
        print(json.dumps(rec, ensure_ascii=False), flush=True)
        log.write(json.dumps(rec, ensure_ascii=False) + "\n")
        log.flush()
        if metrics["CIDEr-D"] > best:
            best = metrics["CIDEr-D"]
            model.save(out_dir)
            write_predictions(records, out_dir / "val_predictions.jsonl")
    log.close()
    return best
