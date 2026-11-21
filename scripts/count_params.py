"""Count the trainable parameters of the 2024 architecture (CNN + attention GRU).

The frozen ResNet-101 is replaced by an identity, since it is not trained; the count covers
the encoder projection, embedding, attention, GRU and output layers with a 10,000-word
vocabulary, as in the 2024 notebooks.

    python scripts/count_params.py
"""

from torch import nn

from urducap.models.legacy import LegacyCaptioner, Vocab

model = LegacyCaptioner(Vocab([f"w{i}" for i in range(10000)]), backbone=nn.Identity(), feat_dim=2048)
print(sum(p.numel() for p in model.parameters() if p.requires_grad))
