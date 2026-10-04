"""Direct endpoint tests for typed exception handling in REST API create routes."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from ipfs_datasets_py.optimizers.api.rest_api import APIServer, EntityRequest, RelationshipRequest


def _endpoint(app, path: str, method: str):
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path == path and method.upper() in route.methods:
            return route.endpoint
    raise AssertionError(f"Route {method} {path} not found")


def test_create_entity_endpoint_maps_value_error_to_http_400(monkeypatch) -> None:
    server = APIServer(title="Typed Exception API", version="test")

    def _raise_value_error(_entity):
        raise ValueError("entity invalid")

    monkeypatch.setattr(server.entity_store, "create", _raise_value_error)
    create_entity = _endpoint(server.app, "/entities", "POST")

    with pytest.raises(HTTPException) as exc:
        create_entity(EntityRequest(name="Alice", entity_type="person", confidence=0.9))

    assert exc.value.status_code == 400
    assert "entity invalid" in exc.value.detail


def test_create_relationship_endpoint_maps_type_error_to_http_400(monkeypatch) -> None:
    server = APIServer(title="Typed Exception API", version="test")

    def _raise_type_error(_relationship):
        raise TypeError("relationship invalid type")

    monkeypatch.setattr(server.relationship_store, "create", _raise_type_error)
    create_relationship = _endpoint(server.app, "/relationships", "POST")

    with pytest.raises(HTTPException) as exc:
        create_relationship(
            RelationshipRequest(
                source_id="e1",
                target_id="e2",
                relationship_type="related_to",
                confidence=0.8,
            )
        )

    assert exc.value.status_code == 400
    assert "relationship invalid type" in exc.value.detail
