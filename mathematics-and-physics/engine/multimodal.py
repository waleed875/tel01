"""First multimodal language-model foundation with randomly initialized weights.

Uses local image patches as causal *prefix tokens* to the existing bytewise GPT.
Text tokens attend to image patches. The module is trainable end-to-end but
UNTRAINED by default and not yet connected to the production chat UI.

NO PRETRAINED MODEL WEIGHTS, no cloud APIs, no external downloads.
"""
from dataclasses import asdict

import torch
from torch import nn
from torch.nn import functional as F

from .model import GPT, GPTConfig


class MultimodalGPT(nn.Module):
    def __init__(self, config: GPTConfig, *, image_size: int = 64,
                 patch_size: int = 16):
        super().__init__()
        if config.vocab_size != 256:
            raise ValueError("Requires local byte-tokenizer vocabulary 256")
        if image_size % patch_size:
            raise ValueError("Image size must divide evenly into patches")
        patch_count = (image_size // patch_size) ** 2
        if patch_count + 2 >= config.block_size:
            raise ValueError("Block size must fit visual prefix and text")
        self.image_size = image_size
        self.patch_size = patch_size
        self.patch_count = patch_count
        self.language = GPT(config)
        self.visual_patch = nn.Conv2d(3, config.n_embd, patch_size, patch_size)
        self.visual_norm = nn.LayerNorm(config.n_embd)

    def forward(self, images: torch.Tensor, idx: torch.Tensor,
                targets: torch.Tensor | None = None):
        if (images.ndim != 4 or images.shape[1:] !=
                (3, self.image_size, self.image_size)):
            raise ValueError("Expected normalized RGB images at configured resolution")
        if idx.ndim != 2 or idx.dtype != torch.long:
            raise ValueError("Expected text byte indices of shape [batch,length]")
        if images.size(0) != idx.size(0):
            raise ValueError("Image/text batch size mismatch")
        batch, tokens = idx.shape
        total = self.patch_count + tokens
        if not tokens or total > self.language.config.block_size:
            raise ValueError("Too many text tokens for visual context")
        visual = self.visual_norm(
            self.visual_patch(images).flatten(2).transpose(1, 2))
        text = self.language.transformer.wte(idx)
        x = torch.cat((visual, text), dim=1)
        pos = torch.arange(total, device=idx.device)
        x = self.language.transformer.drop(
            x + self.language.transformer.wpe(pos))
        for layer in self.language.transformer.h:
            x = layer(x)
        x = self.language.transformer.ln_f(x)
        logits = self.language.lm_head(x[:, self.patch_count:, :])
        loss = None
        if targets is not None:
            if targets.shape != idx.shape:
                raise ValueError("Target token shape mismatch")
            loss = F.cross_entropy(
                logits.reshape(-1, logits.size(-1)),
                targets.reshape(-1), ignore_index=-1)
        return logits, loss

    @torch.inference_mode()
    def generate(self, images: torch.Tensor, idx: torch.Tensor,
                 max_new_tokens: int = 48, top_k: int = 32):
        self.eval()
        if idx.size(1) == 0:
            raise ValueError("Prompt must contain text")
        for _ in range(max_new_tokens):
            keep = self.language.config.block_size - self.patch_count
            text = idx[:, -keep:]
            logits, _ = self(images, text)
            last = logits[:, -1, :]
            values, _ = torch.topk(last, min(top_k, last.size(-1)))
            last = last.masked_fill(last < values[:, -1:], -torch.inf)
            next_token = torch.multinomial(torch.softmax(last, -1), 1)
            idx = torch.cat((idx, next_token), dim=1)
        return idx
