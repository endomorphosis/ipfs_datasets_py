"""New gates preserve default semantic targets and fixed capability policy."""
from copy import deepcopy

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import family_training_v5 as previous
from ipfs_datasets_py.logic.formalization.autoencoder import family_training_v6 as current
from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lake_v4 as gate
from ipfs_datasets_py.logic.formalization.autoencoder import projection_validation_contract_v3 as old_policy
from ipfs_datasets_py.logic.formalization.autoencoder import projection_validation_contract_v4 as policy
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_reconstruction_panel as panel


@pytest.mark.parametrize('domain', panel.DOMAINS)
def test_absent_guarded_declaration_preserves_every_prior_payload_and_capability_requirement(domain):
    inputs = panel.source_inputs(panel.rows(domain, 'train')[0])
    old = previous.prepare_family_training_targets_v5(domain, **inputs)
    report = current.prepare_family_training_targets_v6(domain, **inputs)
    def logical_rows(value):
        return [{k: v for k, v in row.items() if k not in {'source_digest', 'target_sha256'}}
                for row in value['projections']]
    assert logical_rows(report) == logical_rows(old)
    assert report['guarded_effect_binding_input'] is None
    assert report['superseded_guarded_observations'] == []
    assert len(report['requested_families']) == len(report['family_inventory']) == 40
    old_floor = old_policy.domain_projection_policy(domain)['minimum_batch_floor']
    assert policy.domain_projection_policy(domain)['minimum_batch_floor'] == old_floor
    current.validate_family_training_report_v6(report, **inputs)


def test_a_rehashed_old_report_cannot_be_relabelled_as_current_source_evidence():
    inputs = panel.source_inputs(panel.rows('intent_ir', 'train')[0])
    report = deepcopy(previous.prepare_family_training_targets_v5('intent_ir', **inputs))
    report['schema'] = current.SCHEMA
    report['report_sha256'] = current.core._sha({k: v for k, v in report.items() if k != 'report_sha256'})
    with pytest.raises(ValueError, match='v6 producer pin differs'):
        gate.prepare_native_family_lean(report, source_inputs=inputs)


def test_guarded_effect_mappings_cannot_be_supplied_as_mutable_unbound_dicts():
    inputs = panel.source_inputs(panel.rows('intent_ir', 'train')[0])
    with pytest.raises(ValueError, match='immutable guarded effect bindings'):
        current.prepare_family_training_targets_v6('intent_ir', guarded_effect_bindings={}, **inputs)
