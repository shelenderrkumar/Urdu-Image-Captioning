"""Captioning models. Each one implements :class:`urducap.models.base.Captioner`."""

KINDS = ("legacy", "encdec", "vlm")


def build(kind: str, **kwargs):
    if kind == "legacy":
        from .legacy import LegacyCaptioner

        return LegacyCaptioner.from_config(**kwargs)
    if kind == "encdec":
        from .encdec import EncDecCaptioner

        return EncDecCaptioner.from_pretrained(**kwargs)
    if kind == "vlm":
        from .vlm import VLMCaptioner

        return VLMCaptioner.from_pretrained(**kwargs)
    raise ValueError(f"unknown model kind {kind!r}; choose from {KINDS}")
