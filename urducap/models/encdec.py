"""SigLIP 2 image encoder + mBART-50 decoder, joined by cross-attention.

mBART-50 was pre-trained on 50 languages including Urdu (``ur_PK``), so its decoder
already writes fluent Urdu; its cross-attention layers were trained to read an encoder's
states. We feed it SigLIP 2 patch embeddings through a small projector instead of a text
encoder, and fine-tune. Only the projector and the decoder layers are trained: the image
encoder and the 250k-word embedding table stay frozen.
"""

import torch
from torch import nn

from .base import Captioner

VISION = "google/siglip2-base-patch16-224"
DECODER = "facebook/mbart-large-50"
URDU = "ur_PK"


class EncDecCaptioner(Captioner):
    kind = "encdec"

    def __init__(self, vision, decoder, tokenizer, image_processor, names: dict, freeze_vision=True):
        super().__init__()
        self.vision = vision
        self.decoder = decoder
        self.tokenizer = tokenizer
        self.image_processor = image_processor
        self.names = names
        v_dim = vision.config.hidden_size
        d_dim = decoder.config.d_model
        self.proj = nn.Sequential(nn.LayerNorm(v_dim), nn.Linear(v_dim, d_dim))
        self.vision.requires_grad_(not freeze_vision)
        self.decoder.get_input_embeddings().requires_grad_(False)
        # lm_head is tied to the embeddings in mBART; keep it frozen with them.
        self.decoder.get_output_embeddings().requires_grad_(False)
        eos = tokenizer.eos_token_id
        # mBART-50 targets are decoded from "</s> ur_PK ...": the language code is forced.
        self.prompt = [eos, tokenizer.convert_tokens_to_ids(URDU)]

    @classmethod
    def from_pretrained(cls, vision: str = VISION, decoder: str = DECODER, freeze_vision=True):
        from transformers import AutoImageProcessor, AutoModel, AutoTokenizer, MBartForCausalLM

        v = AutoModel.from_pretrained(vision)
        v = getattr(v, "vision_model", v)
        d = MBartForCausalLM.from_pretrained(decoder, add_cross_attention=True, is_decoder=True)
        tok = AutoTokenizer.from_pretrained(decoder)
        proc = AutoImageProcessor.from_pretrained(vision)
        return cls(v, d, tok, proc, {"vision": vision, "decoder": decoder}, freeze_vision)

    def config(self) -> dict:
        return dict(self.names)

    def encode_images(self, pixel_values: torch.Tensor) -> torch.Tensor:
        return self.proj(self.vision(pixel_values=pixel_values).last_hidden_state)

    def collate(self, images, captions=None):
        batch = {"pixel_values": self.image_processor(images, return_tensors="pt")["pixel_values"]}
        if captions is None:
            return batch
        eos, pad = self.tokenizer.eos_token_id, self.tokenizer.pad_token_id
        seqs = [
            self.prompt + self.tokenizer(c, add_special_tokens=False).input_ids[:62] + [eos] for c in captions
        ]
        width = max(len(s) for s in seqs) - 1
        ids = torch.full((len(seqs), width), pad)
        labels = torch.full((len(seqs), width), -100)
        mask = torch.zeros((len(seqs), width), dtype=torch.long)
        for i, s in enumerate(seqs):
            n = len(s) - 1
            ids[i, :n] = torch.tensor(s[:-1])
            labels[i, :n] = torch.tensor(s[1:])
            mask[i, :n] = 1
        # Position 0 predicts the language code, which is forced, not learned.
        labels[:, 0] = -100
        batch.update(input_ids=ids, attention_mask=mask, labels=labels)
        return batch

    def loss(self, batch):
        enc = self.encode_images(batch["pixel_values"])
        out = self.decoder(
            input_ids=batch["input_ids"],
            attention_mask=batch["attention_mask"],
            encoder_hidden_states=enc,
            labels=batch["labels"],
        )
        return out.loss

    @torch.no_grad()
    def generate(self, batch, max_new_tokens=40, num_beams=3):
        enc = self.encode_images(batch["pixel_values"])
        from transformers import DynamicCache, EncoderDecoderCache

        prompt = torch.tensor([self.prompt], device=enc.device).expand(enc.shape[0], -1)
        out = self.decoder.generate(
            # generate() would otherwise create a decoder-only cache, and the cross-attention
            # keys would be appended to the self-attention cache, shifting every position.
            past_key_values=EncoderDecoderCache(DynamicCache(), DynamicCache()),
            input_ids=prompt,
            attention_mask=torch.ones_like(prompt),
            encoder_hidden_states=enc,
            max_new_tokens=max_new_tokens,
            num_beams=num_beams,
            eos_token_id=self.tokenizer.eos_token_id,
            pad_token_id=self.tokenizer.pad_token_id,
            do_sample=False,
        )
        return self.tokenizer.batch_decode(out[:, len(self.prompt) :], skip_special_tokens=True)
