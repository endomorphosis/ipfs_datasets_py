"""Train-only ordered copy supervision, independent of any inference parser.

The auxiliary objective aligns an exact-token longest common subsequence. It
never forces unmatched or reordered fields into an alignment. Reserved IR
control values, tags, punctuation, padding, and direction tokens are excluded.
Repeated tokens receive distinct source occurrences. Coverage is charged only
on aligned target steps, so generator-only tokens do not consume copy capacity.
"""
from functools import lru_cache
import math
from types import SimpleNamespace
from . import autoencoder_paired_copy as shared

# Conservative cross-domain control words: a content occurrence with the same
# spelling is omitted from auxiliary supervision, never assigned a wrong role.
CONTROL = frozenset({'unspecified', 'intended', 'required', 'permitted', 'recommended',
                     'forbidden', 'prohibited', 'obligatory', 'true', 'false', 'null'})


def eligible(token):
    return not token.startswith('<') and token not in CONTROL and any(c.isalnum() for c in token)


def validate_settings(settings):
    if type(settings) is not dict or set(settings) != {'alignment_weight', 'coverage_weight'}:
        raise ValueError('closed alignment objective settings required')
    if any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in settings.values()):
        raise ValueError('bounded finite auxiliary weights required')
    return {k: float(v) for k, v in settings.items()}


@lru_cache(maxsize=32768)
def ordered_matches(source, target):
    """Return (target position, source position), each occurrence at most once."""
    n, m = len(source), len(target)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            match = source[i] == target[j] and eligible(source[i])
            dp[i][j] = 1 + dp[i+1][j+1] if match else max(dp[i+1][j], dp[i][j+1])
    i = j = 0
    result = []
    while i < n and j < m:
        if source[i] == target[j] and eligible(source[i]):
            result.append((j, i)); i += 1; j += 1
        elif dp[i+1][j] >= dp[i][j+1]:
            i += 1
        else:
            j += 1
    return tuple(result)


def batch(torch, records, vocabulary, *, generator=None, dropout=0.0):
    positions = {word: index for index, word in enumerate(vocabulary)}
    inputs, copy_inputs, outputs, sizes, aligned = [], [], [], [], []
    counts = {'encode': 0, 'decode': 0}
    for row, source, target in records:
        matches = ordered_matches(tuple(source), tuple(target))
        # Only tokens actually copied in the paired training target are hidden.
        # Source cues transformed into other labels remain available to the GRU.
        choices = sorted({source[i] for _, i in matches})
        masked = set()
        if dropout:
            shared._require(generator is not None, 'seeded training dropout required')
            masked = {token for token, draw in zip(choices, torch.rand(len(choices), generator=generator).tolist()) if draw < dropout}
        source_ids, copy_ids, extended, extra_ids = shared._source_ids(source, vocabulary, row['direction'], masked=masked)
        target_ids = [extra_ids[token] if token in extra_ids else positions.get(token, 3) for token in target]
        alignment = [-1] * (len(target) + 1)  # final EOS is never aligned
        for target_position, source_position in matches:
            alignment[target_position] = source_position + 1  # direction token
        inputs.append(source_ids); copy_inputs.append(copy_ids); outputs.append([1] + target_ids + [2])
        sizes.append(len(vocabulary) + len(extended)); aligned.append(alignment)
        counts[row['direction']] += len(masked)
    def pad(rows, fill=0):
        width = max(map(len, rows))
        return torch.tensor([row + [fill] * (width-len(row)) for row in rows], dtype=torch.long)
    source = pad(inputs)
    mask = source != 0
    mask[:, 0] = False
    return (source, torch.tensor(list(map(len, inputs))), pad(copy_inputs), pad(outputs),
            mask, max(sizes), pad(aligned, -1), counts)


def auxiliary_losses(torch, attention, alignment, source_mask):
    selected = alignment >= 0
    if not bool(selected.any()):
        zero = attention.sum() * 0
        return zero, zero
    target_positions = alignment.clamp_min(0)
    if bool((selected & ~source_mask.gather(1, target_positions)).any()):
        raise ValueError('alignment cannot target direction or padding')
    mass = attention.gather(2, target_positions.unsqueeze(-1)).squeeze(-1)
    align_loss = -mass[selected].clamp_min(1e-30).log().mean()
    observed = (attention * selected.unsqueeze(-1)).sum(1)
    expected = torch.zeros_like(observed)
    expected.scatter_add_(1, target_positions, selected.to(attention.dtype))
    # Aggregate under/over-coverage over real input positions only. Legitimate
    # repeated tokens have separate positions and therefore separate capacity.
    coverage = ((observed - expected).abs() * source_mask).sum() / (2 * selected.sum())
    return align_loss, coverage


def loss(torch, model, batch, settings):
    from .modal_autoencoder_cuda import _loss_chunk
    source, lengths, copied, target, mask, size, alignment, _ = batch
    encoded, hidden = model.encode(source, lengths)
    probabilities, _, _, _, attention, _ = model.decode(target[:, :-1], hidden, encoded, mask, copied, size)
    shared._require(bool(torch.isfinite(probabilities).all()), 'nonfinite aligned probabilities')
    observed = probabilities.clamp_min(1e-30).log().reshape(-1, size)
    expected = target[:, 1:].reshape(-1)
    keep = expected != 0
    observed, expected = observed[keep], expected[keep]
    count = len(expected)
    state = SimpleNamespace(torch=torch, device=torch.device('cpu'),
        family_targets=torch.nn.functional.one_hot(expected, num_classes=size).float(),
        family_mask=torch.ones(count, dtype=torch.bool))
    parameters = list(model.parameters())
    session = SimpleNamespace(blocks={}, parameters=parameters, parameter_count=sum(p.numel() for p in parameters))
    empty = observed.new_zeros((count, 0))
    ce, _, calls = _loss_chunk(state, session, (empty, observed, empty), {'family_logits'}, 0, count, count, 0., 0., False)
    align, coverage = auxiliary_losses(torch, attention, alignment, mask)
    return ce + settings['alignment_weight'] * align + settings['coverage_weight'] * coverage, calls, count
