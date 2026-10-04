"""Bounded float32 currentness checks using exact CUDA integer views.

CUDA compares the complete float32 bit patterns and checks reference finiteness.
Exact matching bits imply current finiteness and preserve signed-zero refusals.
CPU and explicit opt-out retain the numeric, sign-bit and finiteness reference
checks. Every CUDA chunk contributes before one final host scalar decision.

The caller owns immutable reference custody, model/storage identity, leases,
process/thread and boundary checks. This helper provides no execution, resource,
performance or proof attestation, and retains no successful-check cache.
"""
from __future__ import annotations

import hashlib
from pathlib import Path


SCHEMA = "owned-tensor-bitwise-value-guard/v1"
MAX_TENSORS = 16384
MAX_STATE_BYTES = 16 * 1024**3
MAX_TEMPORARY_BYTES = 512 * 1024**2
MAX_REDUCTION_SCALARS = 65536


def _source_sha256():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


_SOURCE_AT_IMPORT = _source_sha256()


def inference_implementation():
    if _source_sha256() != _SOURCE_AT_IMPORT:
        raise ValueError("owned tensor bitwise guard source changed since import")
    return {"schema": "owned-tensor-bitwise-guard-implementation/v1",
            "source_sha256": _SOURCE_AT_IMPORT,
            "comparison": "finite-float32-exact-bits-with-reference-finiteness/v1"}


def _positive_limit(value, maximum, label):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f"bounded positive {label} required")
    return value


def _plan(torch, state, reference, *, optimized, max_tensors,
          max_total_bytes, max_temporary_bytes):
    if type(optimized) is not bool:
        raise ValueError("optimized must be boolean")
    max_tensors = _positive_limit(max_tensors, MAX_TENSORS, "tensor limit")
    max_total_bytes = _positive_limit(max_total_bytes, MAX_STATE_BYTES, "state byte limit")
    max_temporary_bytes = _positive_limit(max_temporary_bytes, MAX_TEMPORARY_BYTES,
                                          "comparison temporary byte limit")
    if (type(state) is not dict or type(reference) is not dict
            or not 1 <= len(state) <= max_tensors or state.keys() != reference.keys()
            or any(type(name) is not str or not name or len(name) > 1024 for name in state)):
        raise ValueError("bounded matching ordinary named tensor states required")
    device, total_bytes, largest, records = None, 0, 0, []
    # Complete admission precedes reshaping, dtype views and comparisons.
    for name, value in state.items():
        expected = reference[name]
        if not isinstance(value, torch.Tensor) or not isinstance(expected, torch.Tensor):
            raise ValueError("ordinary tensor state/reference values required")
        current_device = str(value.device)
        if (value.device.type not in ("cpu", "cuda") or str(expected.device) != current_device
                or (device is not None and device != current_device)):
            raise ValueError("one supported CPU or CUDA device required")
        device = current_device
        if (value.dtype != torch.float32 or expected.dtype != torch.float32
                or tuple(value.shape) != tuple(expected.shape)
                or value.layout != torch.strided or expected.layout != torch.strided
                or not value.is_contiguous() or not expected.is_contiguous()):
            raise ValueError("matching contiguous strided float32 tensors required")
        count = value.numel()
        if type(count) is not int or count < 0 or value.element_size() != 4 or expected.element_size() != 4:
            raise ValueError("closed float32 tensor metadata required")
        if count and value.untyped_storage().data_ptr() == expected.untyped_storage().data_ptr():
            raise ValueError("state and reference must own separate storage")
        total_bytes += count * 8
        if total_bytes > max_total_bytes:
            raise ValueError("owned tensor state exceeds admitted byte limit")
        largest = max(largest, count)
        records.append((value, expected, count))
    cuda_reduction = optimized and device.startswith("cuda:")
    if cuda_reduction:
        # A dtype view reinterprets physical storage, so unresolved lazy value
        # flags cannot enter this path. CPU/opt-out semantics are unchanged.
        if any(value.is_conj() or value.is_neg() or expected.is_conj() or expected.is_neg()
               for value, expected, _ in records):
            raise ValueError("resolved physical float32 tensor values required for integer views")
    # Retain the existing numeric guard's conservative admission and chunks.
    # Integer views share storage. Explicit per-element results are one bool
    # equality and one bool finiteness mask; eight bytes/element also reserve
    # allowance for backend predicate temporaries. Four bytes per reduction
    # scalar cover retained decisions, their stack and the final reduction.
    # This estimate excludes allocator/kernel workspaces and enforcement.
    chunk_elements = max(1, min(max(1, largest), max_temporary_bytes // 16))
    scalar_count = sum(max(1, (count + chunk_elements - 1) // chunk_elements)
                       for _, _, count in records)
    temporary_bound = (min(largest, chunk_elements) * 8 + scalar_count * 4
                       if cuda_reduction else largest * 8 + len(records) * 4)
    if scalar_count > MAX_REDUCTION_SCALARS or temporary_bound > max_temporary_bytes:
        raise ValueError("exact tensor comparisons exceed admitted temporary bound")
    return records, device, total_bytes, chunk_elements, scalar_count, temporary_bound, cuda_reduction


def check_owned_tensor_bytes(torch, state, reference, *, optimized=True,
                             max_tensors=4096, max_total_bytes=2 * 1024**3,
                             max_temporary_bytes=256 * 1024**2):
    """Refuse changed/nonfinite float32 values with all-value CUDA bit checks.

    ``view(int32)`` reinterprets four bytes; a numeric integer conversion must
    never replace it. Identical finite float32 bits include identical signed
    zeros. A nonfinite reference always refuses even when both bit patterns
    match. Views allocate no tensor storage and weights never move to CPU.
    """
    implementation = inference_implementation()
    (records, device, total_bytes, chunk_elements, scalar_count,
     temporary_bound, cuda_reduction) = _plan(torch, state, reference,
        optimized=optimized, max_tensors=max_tensors, max_total_bytes=max_total_bytes,
        max_temporary_bytes=max_temporary_bytes)
    if cuda_reduction:
        decisions = []
        for value, expected, count in records:
            current, retained = value.reshape(-1), expected.reshape(-1)
            for start in range(0, max(1, count), chunk_elements):
                left = current[start:start + chunk_elements]
                right = retained[start:start + chunk_elements]
                matches = torch.eq(left.view(torch.int32), right.view(torch.int32))
                matches.logical_and_(torch.isfinite(right))
                decisions.append(matches.all())
        # Equality implies current finiteness only after reference finiteness
        # and every current bit contribute to this single complete decision.
        accepted = bool(torch.stack(decisions).all())
        if not accepted:
            raise ValueError("owned tensor values, signed zeros or finite profile changed")
        host_decisions = 1
    else:
        for value, expected, _ in records:
            if (not bool(torch.isfinite(value).all()) or not bool(torch.isfinite(expected).all())
                    or not torch.equal(value, expected)
                    or not torch.equal(torch.signbit(value), torch.signbit(expected))):
                raise ValueError("owned tensor values, signed zeros or finite profile changed")
        host_decisions = len(records) * 4
    return {"schema": SCHEMA,
            "mode": ("cuda_bitwise_single_host_decision" if cuda_reduction else
                     "cpu_reference_checks" if device == "cpu" else "cuda_reference_checks"),
            "comparison_device": device, "tensor_count": len(records),
            "state_and_reference_bytes": total_bytes,
            "comparison_chunk_elements": chunk_elements,
            "comparison_reduction_scalars": scalar_count if cuda_reduction else 0,
            "comparison_temporary_bound_bytes": temporary_bound,
            "host_decision_count": host_decisions,
            "finite_values_checked": True, "signed_zero_checked": True,
            "all_current_values_checked": True,
            "cuda_integer_view_equality": cuda_reduction,
            "cuda_current_finiteness_implied_by_reference_bits": cuda_reduction,
            "mutation_revision_authority": False,
            "autocast_configuration_consulted": False,
            "kernel_resource_enforcement": False, "native_cuda_qualified": False,
            "performance_qualified": False, "proof_authority": False,
            "implementation": implementation}


__all__ = ["check_owned_tensor_bytes", "inference_implementation", "SCHEMA"]
