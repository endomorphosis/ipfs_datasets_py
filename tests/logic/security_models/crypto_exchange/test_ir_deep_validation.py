from copy import deepcopy

import pytest

from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.examples import example_minimal_exchange_model
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.schema import validate_ir



def _remove_deposit_identity(model):
    event = next(item for item in model.events if item['event'] == 'deposit_credited')
    event.pop('txid', None)
    event.pop('deposit_id', None)



def _remove_withdrawal_identity(model):
    event = next(item for item in model.events if item['event'] == 'withdrawal_approved')
    event.pop('withdrawal_id', None)
    event.pop('txid', None)


@pytest.mark.parametrize(
    ('mutator', 'message'),
    [
        (lambda model: model.capabilities.append(dict(model.capabilities[0])), 'Duplicate capability id'),
        (lambda model: model.accounts[0].update({'wallet_id': 'wallet:missing'}), 'references unknown wallet'),
        (lambda model: model.accounts[0].update({'asset_id': 'asset:missing'}), 'references unknown asset'),
        (lambda model: model.accounts[0].update({'balance': -1}), 'balance must be a non-negative integer'),
        (lambda model: model.accounts[0].update({'reservation_requests': [1, -1]}), 'reservation_requests'),
        (lambda model: model.assumptions.append('A404'), 'Unknown assumption id'),
        (lambda model: model.prover_targets.append('fake-prover'), 'Unsupported prover targets'),
        (_remove_deposit_identity, 'deposit_credited events require deposit_id or txid'),
        (_remove_withdrawal_identity, 'withdrawal_approved events require withdrawal_id or txid'),
    ],
)
def test_validate_ir_rejects_invalid_models(mutator, message: str) -> None:
    model = deepcopy(example_minimal_exchange_model())
    mutator(model)
    with pytest.raises(ValueError, match=message):
        validate_ir(model)
