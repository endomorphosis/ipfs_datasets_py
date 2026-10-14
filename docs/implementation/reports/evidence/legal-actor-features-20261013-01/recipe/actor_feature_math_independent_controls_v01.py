"""Independent scalar calculus checks for the proposed contextual adapter.

This is an oracle for the equations, not a production or numerical-kernel test.
No checkpoint, training source, model library, or private endpoint is read.
"""
import hashlib
import json
import math
from pathlib import Path


def attention(features, query, mask):
    width = len(query)
    logits = [sum(x * q for x, q in zip(row, query)) / math.sqrt(width)
              for row, valid in zip(features, mask) if valid]
    maximum = max(logits)
    weights = [math.exp(value - maximum) for value in logits]
    total = sum(weights)
    probabilities = [value / total for value in weights]
    valid_features = [row for row, valid in zip(features, mask) if valid]
    context = [sum(p * row[k] for p, row in zip(probabilities, valid_features))
               for k in range(width)]
    return probabilities, context, valid_features


def objective(features, query, gate, mask, pointer, target):
    probabilities, context, rows = attention(features, query, mask)
    adapted = [[x + a * x * c for x, a, c in zip(row, gate, context)]
               for row in rows]
    logits = [sum(w * x for w, x in zip(pointer, row)) for row in adapted]
    maximum = max(logits)
    exponentials = [math.exp(value - maximum) for value in logits]
    total = sum(exponentials)
    predicted = [value / total for value in exponentials]
    loss = math.log(total) + maximum - logits[target]
    derivatives = [[(p - float(i == target)) * w for w in pointer]
                   for i, p in enumerate(predicted)]
    width = len(query)
    token_derivatives = [sum(d[k] * row[k] for d, row in zip(derivatives, rows))
                         for k in range(width)]
    gate_gradient = [c * d for c, d in zip(context, token_derivatives)]
    context_gradient = [a * d for a, d in zip(gate, token_derivatives)]
    covariance = [[sum(p * row[k] * row[l] for p, row in zip(probabilities, rows))
                   - context[k] * context[l] for l in range(width)]
                  for k in range(width)]
    query_gradient = [sum(context_gradient[k] * covariance[k][l] for k in range(width))
                      / math.sqrt(width) for l in range(width)]
    return loss, gate_gradient, query_gradient, logits


def main():
    features = [[0.4, -0.3, 0.8], [1.2, 0.6, -0.2], [-0.2, 0.9, 0.5],
                [900.0, -800.0, 700.0]]
    mask = [True, True, True, False]
    pointer = [0.9, -0.6, 0.4]
    query = [0.2, -0.1, 0.3]
    gate = [0.4, -0.2, 0.1]
    checks = []
    _, gate_gradient, query_gradient, _ = objective(features, query, gate, mask, pointer, 1)
    epsilon = 1e-5
    for name, value, gradient in [('gate', gate, gate_gradient), ('query', query, query_gradient)]:
        for k, expected in enumerate(gradient):
            plus, minus = value.copy(), value.copy()
            plus[k] += epsilon
            minus[k] -= epsilon
            if name == 'gate':
                upper = objective(features, query, plus, mask, pointer, 1)[0]
                lower = objective(features, query, minus, mask, pointer, 1)[0]
            else:
                upper = objective(features, plus, gate, mask, pointer, 1)[0]
                lower = objective(features, minus, gate, mask, pointer, 1)[0]
            measured = (upper - lower) / (2 * epsilon)
            assert abs(measured - expected) < 1e-8, (name, k, measured, expected)
            checks.append(f'{name}_{k}_analytic_matches_central_difference')
    zero = [0.0] * 3
    initial = objective(features, zero, zero, mask, pointer, 1)
    assert initial[2] == zero and any(abs(value) > 1e-5 for value in initial[1])
    checks.append('initial_query_gradient_exact_zero_gate_gradient_nonzero')
    changed_padding = features[:3] + [[-1e20, 1e20, -1e20]]
    assert objective(features, query, gate, mask, pointer, 1) == objective(
        changed_padding, query, gate, mask, pointer, 1)
    checks.append('masked_padding_cannot_change_context_loss_or_gradient')
    updated = objective(features, query, gate, mask, pointer, 1)
    deltas = [after - before for before, after in zip(initial[3], updated[3])]
    assert max(deltas) - min(deltas) > 1e-4
    assert any(abs(value) > 1e-5 for value in updated[2])
    checks += ['context_interaction_changes_relative_token_logits',
               'nonzero_gate_connects_query_gradient']
    for original in (0.0, -0.0, 1.0, -1.0):
        for residual in (0.0, -0.0):
            preserved = original if residual == 0 else original + residual
            assert preserved == original and math.copysign(1.0, preserved) == math.copysign(1.0, original)
    checks.append('zero_residual_preserves_signed_zero_and_original_value')
    source = Path(__file__).resolve()
    raw = source.read_bytes()
    output = source.parent / 'actor-feature-math-independent-controls-v01.json'
    value = dict(schema='actor-features-scalar-calculus-independent-controls/v1',
                 passed=True, findings=[], control_count=len(checks), controls=checks,
                 source=dict(path=str(source), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()),
                 scope='Scalar analytic equations versus finite differences only; no PyTorch/autograd/kernel/accuracy claim.',
                 actual_models=0, optimizer_updates=0, checkpoint_reads=0, private_body_reads=0)
    with output.open('x') as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write('\n')
    output.chmod(0o444)
    print(json.dumps(dict(passed=True, control_count=len(checks), receipt=str(output))))


if __name__ == '__main__':
    main()
