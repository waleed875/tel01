"""Image patch encoder written locally, initialized with random weights.

No pretrained backbone or online model downloads. This is an experimental
image classifier architecture, NOT a vision-language model.
"""
import torch
from torch import nn


class PatchVisionEncoder(nn.Module):
    def __init__(self, *, image_size=64, patch_size=8, width=64,
                 depth=2, heads=4, num_classes=2):
        super().__init__()
        if image_size % patch_size or width % heads or num_classes < 2:
            raise ValueError("Invalid patch encoder configuration")
        self.image_size = image_size
        self.patch_size = patch_size
        count = (image_size // patch_size) ** 2
        self.patches = nn.Conv2d(3, width, kernel_size=patch_size,
                                 stride=patch_size)
        self.cls = nn.Parameter(torch.zeros(1, 1, width))
        self.positional = nn.Parameter(torch.randn(1, count + 1, width) * 0.02)
        self.encoder = nn.TransformerEncoder(
            nn.TransformerEncoderLayer(
                d_model=width, nhead=heads, dim_feedforward=width * 2,
                dropout=0.0, batch_first=True, activation="gelu",
                norm_first=False),
            num_layers=depth, enable_nested_tensor=False)
        self.head = nn.Linear(width, num_classes)

    def forward(self, rgb):
        if rgb.ndim != 4 or rgb.shape[1:] != (
                3, self.image_size, self.image_size):
            raise ValueError("Expected normalized RGB images at configured size")
        tokens = self.patches(rgb).flatten(2).transpose(1, 2)
        cls = self.cls.expand(len(rgb), -1, -1)
        features = self.encoder(torch.cat([cls, tokens], dim=1) + self.positional)
        return self.head(features[:, 0])
