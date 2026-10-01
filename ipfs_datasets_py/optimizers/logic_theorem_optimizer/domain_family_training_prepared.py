"""Four-domain structural training with explicit numerical backend selection.

Existing native projectors, source decoder recipes and qualification policy are
unchanged. This facade trains separate domain/family projection weights only;
source training options are deliberately outside this API.
"""
from . import intent_family_training_v2 as recipe

SCHEMA = recipe.SCHEMA
DOMAINS = recipe.DOMAINS


def prepare_domain_family_rows(domain_id, rows, *, role="training", requested_families=None):
    recipe._guard()
    return recipe._prepare_domain(domain_id, rows, role=role, requested_families=requested_families)


def train_domain_family_autoencoder(domain_id, training_rows, validation_rows, *,
        output_dir, numerical_backend="v2", parent_descriptor=None, requested_families=None, **settings):
    """Use ``v2`` or ``prepared`` with identical native domain target ownership.

    Continuation requires the same domain/backend, native projection basis,
    producer sources and fixed tuning inventory. Test/canary rows cannot fit or
    select parameters. A family loss is neither a source decoding score nor an
    admission; actual Lake and domain qualification remain separate services.
    """
    return recipe._train_domain(domain_id, training_rows, validation_rows, output_dir=output_dir,
        numerical_backend=numerical_backend, parent_descriptor=parent_descriptor,
        requested_families=requested_families, **settings)


def infer_domain_family_autoencoder(descriptor, rows):
    """Read supplied native targets with the saved domain's separate projection."""
    return recipe._infer_domain(descriptor, rows)


def load_domain_family_recipe(descriptor):
    """Validate the pinned recipe, target artifact and numerical checkpoint."""
    return recipe._read(descriptor)


__all__ = ["prepare_domain_family_rows", "train_domain_family_autoencoder",
           "infer_domain_family_autoencoder", "load_domain_family_recipe", "SCHEMA", "DOMAINS"]
