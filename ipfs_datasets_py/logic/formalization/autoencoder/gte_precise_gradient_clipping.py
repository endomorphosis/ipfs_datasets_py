"""Explicit CPU float32-gradient adapter using a float64 global clipping norm.

This changes the numerical clipping algorithm, not its configured upper bound.
It is restricted to the bounded inherited-interface experiment; it is not a
general replacement for PyTorch clipping. Importing this module does not import
torch, so the existing worker can enforce resource limits first.
"""
from contextlib import contextmanager
import math

ALGORITHM = "cpu-float32-gradient-float64-l2-clip-with-four-epsilon-margin/v1"


def clip_grad_norm_(parameters, max_norm, norm_type=2.0, error_if_nonfinite=False,
                    foreach=None, *, records=None):
    import torch
    if (type(max_norm) not in (int, float) or not math.isfinite(max_norm)
            or max_norm <= 0 or norm_type != 2 or foreach not in (None, False)):
        raise ValueError("finite positive bound, L2 norm and scalar clipping required")
    parameters = list(parameters)
    if not 1 <= len(parameters) <= 64:
        raise ValueError("bounded nonempty parameter list required")
    gradients = [p.grad for p in parameters if p.grad is not None]
    if not gradients or sum(g.numel() for g in gradients) > 16_777_216:
        raise ValueError("bounded nonempty gradient list required")
    for gradient in gradients:
        if (gradient.device.type != "cpu" or gradient.dtype != torch.float32
                or gradient.is_sparse or not bool(torch.isfinite(gradient).all())):
            raise ValueError("finite dense CPU float32 gradients required")

    def norm64():
        norms = [torch.linalg.vector_norm(g.detach().to(torch.float64)) for g in gradients]
        return torch.linalg.vector_norm(torch.stack(norms))

    before = norm64()
    before_float = float(before)
    if not math.isfinite(before_float):
        raise ValueError("finite global gradient norm required")
    clipped = before_float > max_norm
    scale = 1.0
    if clipped:
        scale = max_norm * (1.0 - 4.0 * torch.finfo(torch.float32).eps) / before_float
        with torch.no_grad():
            for gradient in gradients:
                gradient.mul_(scale)
    after_float = float(norm64())
    if not math.isfinite(after_float) or after_float > max_norm:
        raise ValueError("precise gradient clipping exceeded configured bound")
    if records is not None:
        records.append({"algorithm": ALGORITHM, "max_norm": max_norm,
                        "gradient_tensor_count": len(gradients), "norm_before": before_float,
                        "norm_after": after_float, "scale": scale, "clipped": clipped})
    return before


@contextmanager
def installed_clipper(records):
    """Temporarily replace one function in an isolated, already budgeted worker.

    Restoration is unconditional. The runner's external receipt records this
    injection because old checkpoint schemas cannot describe the new algorithm.
    """
    import torch
    previous = torch.nn.utils.clip_grad_norm_
    def adapted(*args, **kwargs):
        return clip_grad_norm_(*args, **kwargs, records=records)
    torch.nn.utils.clip_grad_norm_ = adapted
    try:
        yield
    finally:
        torch.nn.utils.clip_grad_norm_ = previous
