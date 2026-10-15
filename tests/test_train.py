import json

import torch
from PIL import Image
from test_models import CAPTIONS, tiny_legacy

from urducap.data import Item
from urducap.models import base
from urducap.train import predict, score, train


def test_train_loop_saves_best_checkpoint_and_predictions(tmp_path, monkeypatch):
    torch.manual_seed(0)
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    items = []
    for n, (color, caption) in enumerate(zip(("red", "green", "blue"), CAPTIONS, strict=True)):
        Image.new("RGB", (40, 30), color).save(image_dir / f"{n}.jpg")
        items.append(Item(f"{n}.jpg", [caption]))
    model = tiny_legacy()
    best = train(
        model, items, items, image_dir, tmp_path / "run", epochs=40, batch_size=3, lr=1e-2, workers=0
    )
    assert best > 0
    log = [json.loads(line) for line in open(tmp_path / "run" / "train_log.jsonl")]
    assert log[-1]["val"]["images"] == 3
    saved = json.loads((tmp_path / "run" / "model.json").read_text(encoding="utf-8"))
    assert saved["kind"] == "legacy" and saved["units"] == 64

    # Reload through the saved config, swapping only the pretrained backbone for the tiny one.
    from urducap.models import legacy

    monkeypatch.setattr(legacy, "resnet101_backbone", lambda: (model.backbone, 16))
    reloaded = base.load_run(tmp_path / "run")
    records = predict(reloaded, items, image_dir, batch_size=3, workers=0, progress=False)
    assert score(records)["CIDEr-D"] == best
