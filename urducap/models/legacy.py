"""The 2024 model, ported from TensorFlow to PyTorch so it runs in the same evaluation.

ResNet-101 feature grid (frozen) -> linear encoder -> GRU decoder with Bahdanau
attention over the grid (Xu et al., "Show, Attend and Tell", 2015). Word-level
vocabulary of the 10,000 most frequent training words. Same sizes as the notebook:
embedding 256, GRU 512. Two fixes over the original: greedy decoding instead of random
sampling at test time, and the image-level split applied by the trainer.
"""

from collections import Counter

import torch
from torch import nn
from torch.nn import functional as F

from ..text import tokenize
from .base import Captioner

PAD, START, END, UNK = "<pad>", "<start>", "<end>", "<unk>"


class Vocab:
    def __init__(self, words: list[str]):
        self.itos = [PAD, START, END, UNK] + [w for w in words if w not in (PAD, START, END, UNK)]
        self.stoi = {w: i for i, w in enumerate(self.itos)}

    @classmethod
    def build(cls, captions: list[str], size: int = 10000):
        counts = Counter(t for c in captions for t in tokenize(c))
        return cls([w for w, _ in counts.most_common(size)])

    def encode(self, caption: str) -> list[int]:
        unk = self.stoi[UNK]
        return [self.stoi[START]] + [self.stoi.get(t, unk) for t in tokenize(caption)] + [self.stoi[END]]

    def decode(self, ids: list[int]) -> str:
        words = []
        for i in ids:
            w = self.itos[i]
            if w == END:
                break
            if w not in (PAD, START):
                words.append(w)
        return " ".join(words)


class BahdanauAttention(nn.Module):
    def __init__(self, feat_dim, hidden, units):
        super().__init__()
        self.w1 = nn.Linear(feat_dim, units)
        self.w2 = nn.Linear(hidden, units)
        self.v = nn.Linear(units, 1)

    def forward(self, features, hidden):
        score = self.v(torch.tanh(self.w1(features) + self.w2(hidden).unsqueeze(1)))
        weights = score.softmax(dim=1)
        return (weights * features).sum(dim=1), weights.squeeze(-1)


def resnet101_backbone():
    from torchvision.models import ResNet101_Weights, resnet101

    net = resnet101(weights=ResNet101_Weights.IMAGENET1K_V2)
    return nn.Sequential(*list(net.children())[:-2]), 2048


class LegacyCaptioner(Captioner):
    kind = "legacy"

    def __init__(self, vocab: Vocab, backbone=None, feat_dim=2048, embed=256, units=512, size=299):
        super().__init__()
        if backbone is None:
            backbone, feat_dim = resnet101_backbone()
        self.backbone = backbone.requires_grad_(False).eval()
        self.vocab = vocab
        self.size = size
        self.encoder = nn.Linear(feat_dim, embed)
        self.embedding = nn.Embedding(len(vocab.itos), embed)
        self.attention = BahdanauAttention(embed, units, units)
        self.gru = nn.GRUCell(2 * embed, units)
        self.fc1 = nn.Linear(units, units)
        self.fc2 = nn.Linear(units, len(vocab.itos))
        self.units = units
        self._dims = {"embed": embed, "units": units, "size": size}

    @classmethod
    def from_config(cls, vocab: list[str] | None = None, captions: list[str] | None = None, **dims):
        v = Vocab(vocab) if vocab is not None else Vocab.build(captions or [])
        return cls(v, **dims)

    def config(self) -> dict:
        return {"vocab": self.vocab.itos[4:], **self._dims}

    def train(self, mode: bool = True):
        super().train(mode)
        self.backbone.eval()  # frozen batch-norm statistics, as with precomputed features
        return self

    def collate(self, images, captions=None):
        mean = torch.tensor([0.485, 0.456, 0.406]).view(3, 1, 1)
        std = torch.tensor([0.229, 0.224, 0.225]).view(3, 1, 1)
        pix = []
        for im in images:
            t = torch.frombuffer(bytearray(im.resize((self.size, self.size)).tobytes()), dtype=torch.uint8)
            t = t.view(self.size, self.size, 3).permute(2, 0, 1).float() / 255
            pix.append((t - mean) / std)
        batch = {"pixel_values": torch.stack(pix)}
        if captions is not None:
            seqs = [self.vocab.encode(c)[:64] for c in captions]
            ids = torch.zeros((len(seqs), max(map(len, seqs))), dtype=torch.long)
            for i, s in enumerate(seqs):
                ids[i, : len(s)] = torch.tensor(s)
            batch["captions"] = ids
        return batch

    def features(self, pixel_values):
        with torch.no_grad():
            grid = self.backbone(pixel_values)  # B x C x h x w
        return F.relu(self.encoder(grid.flatten(2).transpose(1, 2)))

    def step(self, token, features, hidden):
        context, weights = self.attention(features, hidden)
        hidden = self.gru(torch.cat([context, self.embedding(token)], dim=-1), hidden)
        return self.fc2(self.fc1(hidden)), hidden, weights

    def loss(self, batch):
        feats = self.features(batch["pixel_values"])
        caps = batch["captions"]
        hidden = feats.new_zeros(caps.shape[0], self.units)
        losses = []
        for t in range(caps.shape[1] - 1):  # teacher forcing
            logits, hidden, _ = self.step(caps[:, t], feats, hidden)
            losses.append(F.cross_entropy(logits, caps[:, t + 1], ignore_index=0, reduction="none"))
        losses = torch.stack(losses, dim=1)
        return losses.sum() / (caps[:, 1:] != 0).sum()

    @torch.no_grad()
    def generate(self, batch, max_new_tokens=40, num_beams=1, return_attention=False):
        feats = self.features(batch["pixel_values"])
        b = feats.shape[0]
        hidden = feats.new_zeros(b, self.units)
        token = torch.full((b,), self.vocab.stoi[START], device=feats.device)
        out, attn = [], []
        for _ in range(max_new_tokens):  # greedy
            logits, hidden, weights = self.step(token, feats, hidden)
            token = logits.argmax(-1)
            out.append(token)
            attn.append(weights)
        ids = torch.stack(out, dim=1).tolist()
        texts = [self.vocab.decode(row) for row in ids]
        return (texts, torch.stack(attn, dim=1)) if return_attention else texts
