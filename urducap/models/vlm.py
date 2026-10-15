"""A small open vision-language model (Qwen3-VL-2B-Instruct) prompted or LoRA-tuned for Urdu.

Zero-shot, the model is asked for a one-sentence Urdu description. For fine-tuning we
train LoRA adapters on the language model's attention and MLP projections, with the
loss on the answer tokens only: the prompt and the image tokens are masked out.
"""

import torch

from .base import Captioner

BASE = "Qwen/Qwen3-VL-2B-Instruct"
# "Describe this picture in one sentence in Urdu."
PROMPT = "اس تصویر کو اردو میں ایک جملے میں بیان کریں۔"


def messages(prompt: str, answer: str | None = None) -> list[dict]:
    msgs = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": prompt}]}]
    if answer is not None:
        msgs.append({"role": "assistant", "content": [{"type": "text", "text": answer}]})
    return msgs


def mask_prompt(input_ids: torch.Tensor, attention_mask: torch.Tensor, prompt_lens: list[int]):
    """Labels equal to the inputs, with prompt tokens and padding replaced by -100."""
    labels = input_ids.clone()
    labels[attention_mask == 0] = -100
    for i, n in enumerate(prompt_lens):
        # Left or right padding: the prompt starts at the first non-pad position.
        start = int(attention_mask[i].nonzero()[0])
        labels[i, : start + n] = -100
    return labels


class VLMCaptioner(Captioner):
    kind = "vlm"

    def __init__(self, model, processor, base: str, lora: dict | None):
        super().__init__()
        self.model = model
        self.processor = processor
        self.base = base
        self.lora = lora

    @classmethod
    def from_pretrained(cls, base: str = BASE, lora: dict | None = None):
        from transformers import AutoModelForImageTextToText, AutoProcessor

        dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
        model = AutoModelForImageTextToText.from_pretrained(base, dtype=dtype)
        processor = AutoProcessor.from_pretrained(base)
        processor.tokenizer.padding_side = "left"  # batched generation needs left padding
        model.requires_grad_(False)
        if lora:
            from peft import LoraConfig, get_peft_model

            model = get_peft_model(
                model,
                LoraConfig(
                    r=lora.get("r", 16),
                    lora_alpha=lora.get("alpha", 32),
                    lora_dropout=0.05,
                    target_modules=r".*language_model.*\.(q_proj|k_proj|v_proj|o_proj|gate_proj|up_proj|down_proj)",
                ),
            )
        return cls(model, processor, base, lora)

    def config(self) -> dict:
        return {"base": self.base, "lora": self.lora}

    def _chat(self, msgs, generation):
        return self.processor.apply_chat_template(msgs, tokenize=False, add_generation_prompt=generation)

    def collate(self, images, captions=None):
        if captions is None:
            texts = [self._chat(messages(PROMPT), True) for _ in images]
            return dict(self.processor(text=texts, images=images, padding=True, return_tensors="pt"))
        texts = [self._chat(messages(PROMPT, c), False) for c in captions]
        batch = dict(self.processor(text=texts, images=images, padding=True, return_tensors="pt"))
        # The prompt's token count, image tokens included, is the same with or without
        # the answer, so tokenise the prompt alone to find where the answer starts.
        prompt_lens = [
            self.processor(text=[self._chat(messages(PROMPT), True)], images=[im], return_tensors="pt")[
                "input_ids"
            ].shape[1]
            for im in images
        ]
        batch["labels"] = mask_prompt(batch["input_ids"], batch["attention_mask"], prompt_lens)
        return batch

    def loss(self, batch):
        return self.model(**batch).loss

    @torch.no_grad()
    def generate(self, batch, max_new_tokens=40, num_beams=1):
        out = self.model.generate(
            **batch, max_new_tokens=max_new_tokens, num_beams=num_beams, do_sample=False
        )
        new = out[:, batch["input_ids"].shape[1] :]
        texts = self.processor.batch_decode(new, skip_special_tokens=True)
        return [t.strip().split("\n")[0] for t in texts]
