"""Shared loss helpers for cadence models."""

from __future__ import annotations

import torch
from torch.nn import functional as F


def masked_smooth_l1(pred: torch.Tensor, target: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    expanded_mask = mask.unsqueeze(-1).expand_as(pred) if pred.ndim == 3 else mask
    if not expanded_mask.any():
        return pred.sum() * 0.0
    return F.smooth_l1_loss(pred[expanded_mask], target[expanded_mask])
