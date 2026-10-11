"""Long source-unit inference is an explicit profile, not a changed default."""
import pytest

from ipfs_datasets_py.logic.software_contracts import codebase_source_384 as shared
from ipfs_datasets_py.logic.software_contracts import codebase_source_units_384 as units


@pytest.mark.parametrize('profile, timeout', [(None, 601), ('unknown', 600), (True, 600),
    (shared.FORMALIZATION_BUDGET_PROFILE, 3601), (shared.FORMALIZATION_BUDGET_PROFILE, float('inf')),
    (shared.FORMALIZATION_BUDGET_PROFILE, True)])
def test_invalid_budget_is_refused_before_native_owners(profile, timeout, monkeypatch):
    monkeypatch.setattr(shared, '_owners', lambda *args: pytest.fail('invalid deadline touched native owner'))
    with pytest.raises(ValueError):
        units.infer_shared_parent_units(None, '/absent', expected_head=None, registry=None, version_id=None,
            paths=[], embedding_snapshot=None, timeout_seconds=timeout, budget_profile=profile)


@pytest.mark.parametrize('profile, timeout', [(None, 600), (shared.FORMALIZATION_BUDGET_PROFILE, 3600)])
def test_selected_bounded_deadline_reaches_independent_owner_validation(profile, timeout, monkeypatch):
    class OwnerBoundaryReached(RuntimeError): pass
    def owner(*args): raise OwnerBoundaryReached()
    monkeypatch.setattr(shared, '_owners', owner)
    with pytest.raises(OwnerBoundaryReached):
        units.infer_shared_parent_units(None, '/absent', expected_head=None, registry=None, version_id=None,
            paths=[], embedding_snapshot=None, timeout_seconds=timeout, budget_profile=profile)


def test_training_does_not_inherit_inference_profile():
    with pytest.raises(ValueError, match='bounded positive deadline'):
        shared.train_current_source384(None, '/absent', expected_head=None, registry=None,
            parent_version_id=None, selections=[], operation_id='training', embedding_snapshot=None,
            timeout_seconds=601)
