"""Property-style randomized invariants for Entity/Relationship."""

from __future__ import annotations

import json
import random
import string

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity, Relationship


def _rand_text(rng: random.Random, min_len: int = 3, max_len: int = 16) -> str:
    length = rng.randint(min_len, max_len)
    alphabet = string.ascii_letters + string.digits + "_-"
    return "".join(rng.choice(alphabet) for _ in range(length))


def test_entity_roundtrip_and_hash_invariants_randomized() -> None:
    rng = random.Random(42)

    for _ in range(100):
        eid = _rand_text(rng)
        source_span = (rng.randint(0, 50), rng.randint(51, 100))
        entity = Entity(
            id=eid,
            type=_rand_text(rng),
            text=_rand_text(rng, 5, 20),
            properties={"k": _rand_text(rng), "n": rng.randint(0, 999)},
            confidence=rng.random(),
            source_span=source_span,
            last_seen=float(rng.randint(1, 10_000)),
        )

        restored = Entity.from_dict(entity.to_dict())
        restored_from_ctor = Entity(**entity.to_dict())

        assert restored == entity
        assert restored_from_ctor == entity
        assert hash(entity) == hash(entity.id)
        assert json.loads(entity.to_json())["id"] == entity.id


def test_relationship_roundtrip_and_hash_invariants_randomized() -> None:
    rng = random.Random(43)

    for _ in range(100):
        rid = _rand_text(rng)
        relationship = Relationship(
            id=rid,
            source_id=_rand_text(rng),
            target_id=_rand_text(rng),
            type=_rand_text(rng),
            properties={"weight": rng.random(), "label": _rand_text(rng)},
            confidence=rng.random(),
            direction=rng.choice(["unknown", "undirected", "subject_to_object"]),
        )

        restored = Relationship.from_dict(relationship.to_dict())
        restored_from_ctor = Relationship(**relationship.to_dict())

        assert restored == relationship
        assert restored_from_ctor == relationship
        assert hash(relationship) == hash(relationship.id)
        assert json.loads(relationship.to_json())["id"] == relationship.id
