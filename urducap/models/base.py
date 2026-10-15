"""The interface the trainer and evaluator use, so all three models share one loop."""

import json
from pathlib import Path

import torch
from torch import nn


class Captioner(nn.Module):
    kind: str = ""

    def collate(self, images: list, captions: list[str] | None) -> dict:
        """Turn PIL images (and target captions when training) into a tensor batch."""
        raise NotImplementedError

    def loss(self, batch: dict) -> torch.Tensor:
        raise NotImplementedError

    def generate(self, batch: dict, max_new_tokens: int = 40, num_beams: int = 3) -> list[str]:
        raise NotImplementedError

    def config(self) -> dict:
        """Everything needed to rebuild the untrained model (base model names, sizes)."""
        raise NotImplementedError

    # Only trainable tensors are saved: frozen backbones are reloaded from their hub names,
    # so a run directory holds megabytes of adapters instead of gigabytes of copies.
    def save(self, run_dir: str | Path) -> None:
        run_dir = Path(run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        trainable = {n for n, p in self.named_parameters() if p.requires_grad}
        state = {k: v.detach().cpu() for k, v in self.state_dict().items() if k in trainable}
        torch.save(state, run_dir / "trainable.pt")
        (run_dir / "model.json").write_text(
            json.dumps({"kind": self.kind, **self.config()}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load_trainable(self, run_dir: str | Path) -> None:
        state = torch.load(Path(run_dir) / "trainable.pt", map_location="cpu")
        missing = set(state) - set(self.state_dict())
        if missing:
            raise ValueError(f"checkpoint has unknown tensors: {sorted(missing)[:5]}")
        self.load_state_dict(state, strict=False)

    @property
    def device(self) -> torch.device:
        return next(self.parameters()).device


def load_run(run_dir: str | Path) -> Captioner:
    from . import build

    cfg = json.loads((Path(run_dir) / "model.json").read_text(encoding="utf-8"))
    model = build(cfg.pop("kind"), **cfg)
    model.load_trainable(run_dir)
    return model
