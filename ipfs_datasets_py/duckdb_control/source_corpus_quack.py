"""Opt-in source-corpus commands over the existing bounded Quack transport.

Only the transient inbox/reply database is served. Source package decoding,
materialization and verification are explicit owner work outside its pump.
Importing this module does not connect, load an extension or start a listener.
Native listener qualification is separate from offline command validation.
"""
from __future__ import annotations

import uuid

from .autoencoder_quack import (
    _TransientQuackGateway, RegistryTransportClient, RegistryTransportError,
)
from .autoencoder_quack_wire import SCHEMA, QuackWireError, _request as encode_request, parse_request
from .source_corpus_control import SourceCorpusControl


COMMANDS = frozenset({"RegisterSourceExport", "ResolveSourceExport",
                      "ReadSourceVersion", "ReadSourceRows"})


class SourceCorpusQuackGateway(_TransientQuackGateway):
    """One owner-issued source scope per transient loopback endpoint."""

    def __init__(self, control, *, enable_prototype=False):
        if enable_prototype is not True:
            raise RegistryTransportError("source transport requires explicit prototype opt-in")
        if type(control) is not SourceCorpusControl:
            raise RegistryTransportError("source transport requires a typed source owner control")
        self.control = control
        super().__init__()

    def _before_start(self):
        with self.control.catalog.try_owner_access() as acquired:
            if not acquired:
                raise RegistryTransportError("source owner is busy")

    def dispatch(self, envelope):
        request = parse_request(encode_request(envelope))
        if request["command"] not in COMMANDS:
            raise RegistryTransportError("command is outside the source corpus vocabulary")
        return self.control.dispatch(request["command"], request["operation_id"], request["payload"])

    def _expected_error(self, error):
        # Durable mutation may precede a lost/invalid reply. Do not expose
        # private package paths, database diagnostics, SQL or native traces.
        return "source command unavailable; resolve the same operation ID and payload before retrying"

    def status(self):
        return {"schema": SCHEMA, "prototype": True, "runtime_qualified": False,
                "production_activation": False, "admitted": False, "formalized": False,
                "started": self._server is not None, "command_profile": "source_corpus",
                "authorization": "owner_issued_source_scope_bearer",
                "principal_id": self.control.scope.principal_id,
                "package_execution_in_gateway_pump": False,
                "private_catalog_served": False, "transient_gateway_database": True,
                "failure": self._failure, "capability": self.capability}


class SourceCorpusTransportClient(RegistryTransportClient):
    """The same request-bound codec and native client, with source commands."""

    @staticmethod
    def _request_envelope(command, payload, operation_id):
        if type(command) is not str or command not in COMMANDS:
            raise RegistryTransportError("command is outside the source corpus vocabulary")
        try:
            return parse_request(encode_request({"schema": SCHEMA, "request_id": str(uuid.uuid4()),
                                  "operation_id": operation_id, "command": command,
                                  "payload": payload}))
        except QuackWireError as exc:
            raise RegistryTransportError(str(exc)) from exc
