"""Tiny randomly initialised models, so the tests run offline on a CPU in seconds."""

import torch
from torch import nn

from urducap.models.base import load_run
from urducap.models.encdec import URDU, EncDecCaptioner
from urducap.models.legacy import LegacyCaptioner, Vocab
from urducap.models.vlm import mask_prompt

CAPTIONS = ["ایک کتا دوڑ رہا ہے۔", "دو بچے کھیل رہے ہیں۔", "ایک عورت کھڑی ہے۔"]


def tiny_tokenizer():
    from tokenizers import Tokenizer, models, pre_tokenizers
    from transformers import PreTrainedTokenizerFast

    words = sorted({w for c in CAPTIONS for w in c.replace("۔", " ۔").split()})
    vocab = {t: i for i, t in enumerate(["<s>", "<pad>", "</s>", "<unk>", URDU, *words])}
    tok = Tokenizer(models.WordLevel(vocab, unk_token="<unk>"))
    tok.pre_tokenizer = pre_tokenizers.Sequence(
        [pre_tokenizers.WhitespaceSplit(), pre_tokenizers.Split("۔", "isolated")]
    )
    return PreTrainedTokenizerFast(
        tokenizer_object=tok, bos_token="<s>", eos_token="</s>", pad_token="<pad>", unk_token="<unk>"
    )


def tiny_encdec():
    from transformers import (
        MBartConfig,
        MBartForCausalLM,
        SiglipImageProcessor,
        SiglipVisionConfig,
        SiglipVisionModel,
    )

    tok = tiny_tokenizer()
    vision = SiglipVisionModel(
        SiglipVisionConfig(
            hidden_size=32,
            intermediate_size=64,
            num_hidden_layers=1,
            num_attention_heads=2,
            image_size=32,
            patch_size=8,
        )
    )
    dec = MBartForCausalLM(
        MBartConfig(
            vocab_size=len(tok),
            d_model=32,
            decoder_layers=1,
            decoder_attention_heads=2,
            decoder_ffn_dim=64,
            encoder_layers=1,
            encoder_attention_heads=2,
            encoder_ffn_dim=64,
            max_position_embeddings=64,
            pad_token_id=tok.pad_token_id,
            eos_token_id=tok.eos_token_id,
            bos_token_id=0,
            is_decoder=True,
            add_cross_attention=True,
        )
    )
    proc = SiglipImageProcessor(size={"height": 32, "width": 32})
    return EncDecCaptioner(vision, dec, tok, proc, {"vision": "tiny", "decoder": "tiny"})


def overfit(model, images, steps=150, lr=3e-3):
    batch = model.collate(images, CAPTIONS)
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=lr)
    model.train()
    first = None
    for _ in range(steps):
        loss = model.loss(batch)
        first = first if first is not None else loss.item()
        opt.zero_grad()
        loss.backward()
        opt.step()
    return first, loss.item()


def test_encdec_freezes_backbone_and_embeddings():
    m = tiny_encdec()
    assert not any(p.requires_grad for p in m.vision.parameters())
    assert not m.decoder.get_input_embeddings().weight.requires_grad
    assert all(p.requires_grad for p in m.proj.parameters())


def test_encdec_targets_force_language_code(images):
    m = tiny_encdec()
    b = m.collate(images[:1], CAPTIONS[:1])
    ids, labels = b["input_ids"][0].tolist(), b["labels"][0].tolist()
    assert ids[:2] == m.prompt  # "</s> ur_PK" starts the decoder input
    assert labels[0] == -100  # the language code is not a learning target
    assert labels[-1] == m.tokenizer.eos_token_id
    assert ids[1:] == labels[:-1][: len(ids) - 1] or labels[1:-1] == ids[2:]


def test_encdec_learns_and_generates_captions(images):
    torch.manual_seed(0)
    m = tiny_encdec()
    # A 32-wide random embedding table cannot be frozen and still fit; the real one is pre-trained.
    m.decoder.get_input_embeddings().requires_grad_(True)
    first, last = overfit(m, images)
    assert last < first / 5
    m.eval()
    out = m.generate(m.collate(images), max_new_tokens=8, num_beams=2)
    assert [o.replace(" ", "") for o in out] == [c.replace(" ", "") for c in CAPTIONS]


def test_encdec_save_and_reload_only_trainable(tmp_path, images, monkeypatch):
    torch.manual_seed(0)
    m = tiny_encdec()
    overfit(m, images, steps=20)
    m.save(tmp_path)
    state = torch.load(tmp_path / "trainable.pt")
    assert not any(k.startswith("vision.") for k in state)
    monkeypatch.setattr(EncDecCaptioner, "from_pretrained", classmethod(lambda cls, **kw: _fresh(m)))
    reloaded = load_run(tmp_path)
    for k, v in state.items():
        assert torch.equal(reloaded.state_dict()[k], v)


def _fresh(trained):
    torch.manual_seed(1)
    fresh = tiny_encdec()
    fresh.vision.load_state_dict(trained.vision.state_dict())  # frozen weights come from the hub
    return fresh


def tiny_legacy():
    vocab = Vocab.build(CAPTIONS)
    backbone = nn.Sequential(nn.Conv2d(3, 16, 8, stride=8), nn.ReLU())
    return LegacyCaptioner(vocab, backbone=backbone, feat_dim=16, embed=32, units=64, size=32)


def test_vocab_roundtrip():
    v = Vocab.build(CAPTIONS)
    assert v.decode(v.encode(CAPTIONS[0])[1:]) == "ایک کتا دوڑ رہا ہے ۔"
    assert v.encode("نامعلوم")[1] == v.stoi["<unk>"]


def test_legacy_learns_and_generates(images):
    torch.manual_seed(0)
    m = tiny_legacy()
    first, last = overfit(m, images, steps=200, lr=1e-2)
    assert last < first / 5
    m.eval()
    texts, attn = m.generate(m.collate(images), max_new_tokens=8, return_attention=True)
    assert texts == [
        " ".join(Vocab.build(CAPTIONS).decode(Vocab.build(CAPTIONS).encode(c)[1:]).split()) for c in CAPTIONS
    ]
    assert attn.shape == (3, 8, 16)  # one weight per 4x4 grid cell per word
    assert torch.allclose(attn.sum(-1), torch.ones(3, 8))


def test_legacy_backbone_stays_frozen_in_train_mode():
    m = tiny_legacy().train()
    assert not m.backbone.training
    assert not any(p.requires_grad for p in m.backbone.parameters())


def test_vlm_loss_only_on_answer_tokens():
    ids = torch.tensor([[0, 0, 5, 6, 7, 8, 9], [5, 6, 7, 8, 9, 10, 11]])
    mask = torch.tensor([[0, 0, 1, 1, 1, 1, 1], [1, 1, 1, 1, 1, 1, 1]])
    labels = mask_prompt(ids, mask, prompt_lens=[3, 4])
    assert labels.tolist() == [[-100, -100, -100, -100, -100, 8, 9], [-100, -100, -100, -100, 9, 10, 11]]
