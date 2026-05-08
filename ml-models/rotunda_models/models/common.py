"""Shared loss helpers for cadence models."""

from __future__ import annotations

import torch
from torch.nn import functional as F

LOG_DT_SIGMA_MIN = 0.03
LOG_DT_SIGMA_MAX = 1.25


def masked_smooth_l1(pred: torch.Tensor, target: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    """Compute Smooth L1 loss over valid sequence positions only."""
    expanded_mask = mask.unsqueeze(-1).expand_as(pred) if pred.ndim == 3 else mask
    if not expanded_mask.any():
        return pred.sum() * 0.0
    return F.smooth_l1_loss(pred[expanded_mask], target[expanded_mask])


def timing_log_mu(pred: torch.Tensor) -> torch.Tensor:
    """Return the deterministic log-delay prediction for scalar or distribution heads."""
    if is_timing_distribution(pred):
        return pred[..., 0]
    return pred


def is_timing_distribution(pred: torch.Tensor) -> bool:
    """Detect the 2-parameter timing head without confusing [batch, seq] scalars."""
    return (pred.ndim >= 3 and pred.shape[-1] == 2) or (pred.ndim == 1 and pred.shape[0] == 2)


def timing_log_sigma(pred: torch.Tensor) -> torch.Tensor:
    """Map a raw timing-scale head onto a bounded positive log-delay sigma."""
    sigma = LOG_DT_SIGMA_MIN + F.softplus(pred[..., 1])
    return torch.clamp(sigma, max=LOG_DT_SIGMA_MAX)


def masked_timing_loss(pred: torch.Tensor, target: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    """Fit scalar timing with Smooth L1 or lognormal timing with Gaussian NLL."""
    if pred.ndim == target.ndim + 1 and pred.shape[-1] == 2:
        if not mask.any():
            return pred.sum() * 0.0
        mu = pred[..., 0]
        sigma = timing_log_sigma(pred)
        error = (target - mu) / sigma
        nll = 0.5 * error.square() + torch.log(sigma)
        return nll[mask].mean()
    return masked_smooth_l1(pred, target, mask)


def sample_timing_log(
    pred: torch.Tensor,
    temperature: float,
    *,
    generator: torch.Generator | None = None,
) -> torch.Tensor:
    """Sample or deterministically decode one log-delay prediction."""
    mu = timing_log_mu(pred)
    if is_timing_distribution(pred) and temperature > 0:
        sigma = timing_log_sigma(pred) * float(temperature)
        noise = torch.randn(mu.shape, device=mu.device, generator=generator)
        return mu + (sigma * noise)
    return mu
