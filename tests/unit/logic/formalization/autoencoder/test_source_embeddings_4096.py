"""Controlled protocol tests; no model, service, native owner or inference runs."""
import json
import math
import unittest
from unittest.mock import patch

from ipfs_datasets_py.logic.formalization.autoencoder import source_embeddings_4096 as module


def raw(value):
    return json.dumps(value, separators=(",", ":"), allow_nan=False).encode()


class ControlledTransport:
    def __init__(self):
        self.calls = []
        self.responses = {
            "/health": {"status": "ok"},
            "/props": {"model_alias": "leanstral_local", "total_slots": 4,
                "model_path": "/local/models/cid-v1/" + module.MODEL_CID + "/" + module.MODEL_FILENAME,
                "build_info": "controlled-build", "default_generation_settings": {"n_ctx": 32768}},
            "/v1/models": {"data": [{"id": "leanstral_local", "owned_by": "llamacpp",
                "meta": {"n_embd": 4096, "n_vocab": 131072}}]},
        }

    def get(self, path):
        self.calls.append(path)
        return raw(self.responses[path])


class Leanstral4096ProtocolControls(unittest.TestCase):
    def test_current_shape_observes_hidden_width_without_granting_embedding_capability(self):
        transport = ControlledTransport()
        value = module.inspect_embedding_capability(transport)
        self.assertEqual(transport.calls, list(module.GET_PATHS))
        self.assertEqual(value["observed_native_input_dimension"], 4096)
        self.assertIsNone(value["observed_native_output_dimension"])
        self.assertEqual(value["observed_backend_total_slots"], 4)
        self.assertEqual(value["client_concurrency"], 1)
        self.assertEqual(value["transport_scope"], "controlled_protocol_only")
        for field in ("qualified", "production_allowed", "embedding_requests", "generation_requests",
                      "tokenizer_requests", "trained_decoder_head", "proof_authority", "completion_authority"):
            self.assertFalse(value[field])
        for field in ("embedding", "pooling_type", "embd_normalize", "n_embd_out", "device", "n_ubatch"):
            self.assertIn("native_" + field + "_unattested", value["reason_codes"])

    def test_fabricated_native_capability_fields_cannot_bypass_missing_owner_integration(self):
        transport = ControlledTransport()
        transport.responses["/props"].update(embedding=True, pooling_type="last", embd_normalize=2,
            n_embd_out=4096, device="CUDA0", n_ubatch=512)
        value = module.inspect_embedding_capability(transport)
        self.assertFalse(value["production_allowed"])
        self.assertEqual(value["reason_codes"], ["trusted_native_owner_integration_required"])
        with self.assertRaises(module.LeanstralEmbeddingUnavailable):
            module.embed_rows([], owner_verifier=value)

    def test_disabled_mode_and_model_768_metadata_remain_unavailable(self):
        transport = ControlledTransport()
        transport.responses["/props"]["embedding"] = False
        transport.responses["/v1/models"]["data"][0]["meta"]["n_embd"] = 768
        value = module.inspect_embedding_capability(transport)
        self.assertIn("native_embeddings_mode_disabled_or_invalid", value["reason_codes"])
        self.assertIn("native_input_hidden_width_differs", value["reason_codes"])

    def test_malformed_nested_native_metadata_fails_closed(self):
        transport = ControlledTransport()
        transport.responses["/props"]["default_generation_settings"] = None
        with self.assertRaises(ValueError): module.inspect_embedding_capability(transport)

    def test_producer_change_between_readonly_gets_refuses_observation(self):
        transport = ControlledTransport()
        source = module.Path(module.__file__).read_bytes()
        with patch.object(module.Path, "read_bytes", side_effect=[source, source + b"\n"]):
            with self.assertRaisesRegex(ValueError, "producer changed"):
                module.inspect_embedding_capability(transport)

    def test_model_alias_path_or_ambiguous_native_model_cannot_claim_compatibility(self):
        for mutation in (lambda t: t.responses["/props"].update(model_path="/other/model.gguf"),
                         lambda t: t.responses["/props"].update(model_alias="other"),
                         lambda t: t.responses["/v1/models"]["data"].append(t.responses["/v1/models"]["data"][0])):
            transport = ControlledTransport(); mutation(transport)
            value = module.inspect_embedding_capability(transport)
            self.assertFalse(value["production_allowed"])
            self.assertGreater(len(value["reason_codes"]), 7)

    def test_profile_cannot_relabel_768_hash_dimension_or_capacity_as_native4096(self):
        for options in ({"dimension": 768}, {"dimension": True}, {"pooling": "mean"},
                        {"client_concurrency": 4}, {"declared_model_sha256": "0" * 64},
                        {"tokenizer_add_special": 1}):
            with self.assertRaises(ValueError):
                module.Leanstral4096Profile(**options)

    def test_discovery_is_get_only_local_bounded_and_redirect_free(self):
        for origin in ("https://127.0.0.1:8080", "http://example.com:8080", "http://127.0.0.1:8081",
                       "http://127.0.0.1:8080/v1", "http://u:p@127.0.0.1:8080", "http://127.0.0.1:8080?x=1"):
            with self.assertRaises(ValueError):
                module.NativeReadOnlyTransport(origin)
        transport = module.NativeReadOnlyTransport()
        with patch.object(transport._opener, "open") as opened:
            for path in ("/slots", "/tokenize", "/v1/embeddings", "/v1/chat/completions"):
                with self.assertRaises(ValueError): transport.get(path)
            opened.assert_not_called()
        with self.assertRaises(ValueError):
            module._NoRedirect().redirect_request(None, None, 302, "redirect", None, "http://other")

    def test_strict_json_rejects_duplicates_nonfinite_and_oversized_responses(self):
        for value in (b'{"tokens":[1],"tokens":[2]}', b'{"x":NaN}', b'x' * (module.MAX_RESPONSE_BYTES + 1)):
            with self.assertRaises(ValueError): module._decode(value)

    def test_token_diagnostic_binds_exact_ids_and_remains_nonauthoritative(self):
        value = module.validate_token_response(raw({"tokens": [1, 2, 131071]}), vocabulary_size=131072)
        self.assertEqual(value["token_count"], 3)
        self.assertEqual(value["tokens"], [1, 2, 131071])
        self.assertFalse(value["production_allowed"])
        self.assertFalse(value["native_execution_verified"])
        changed = module.validate_token_response(raw({"tokens": [1, 2, 3]}), vocabulary_size=131072)
        self.assertNotEqual(value["token_input_sha256"], changed["token_input_sha256"])

    def test_token_protocol_rejects_empty_truncated_overlength_aliases_and_foreign_ids(self):
        for response in ({"tokens": []}, {"tokens": [True]}, {"tokens": [-1]}, {"tokens": [131072]},
                         {"tokens": [1.0]}, {"tokens": [1] * 513}, {"tokens": [1], "truncated": True}):
            with self.assertRaises(ValueError):
                module.validate_token_response(raw(response), vocabulary_size=131072)

    def vector_response(self, vector):
        return {"object": "list", "model": "leanstral_local", "data": [
            {"object": "embedding", "index": 0, "embedding": vector}],
            "usage": {"prompt_tokens": 3, "total_tokens": 3}}

    def test_exact4096_vector_protocol_never_becomes_native_output_or_device_proof(self):
        vector = [1 / 64] * 4096
        value = module.validate_vector_response(raw(self.vector_response(vector)), expected_token_count=3)
        self.assertEqual(value["dimension"], 4096)
        self.assertFalse(value["production_allowed"])
        self.assertFalse(value["native_output_provenance_verified"])
        self.assertFalse(value["device_execution_verified"])
        with self.assertRaises(module.LeanstralEmbeddingUnavailable):
            module.embed_rows([{"id": "source", "source_text": "x"}], owner_verifier=value)

    def test_padded768_vector_cannot_be_promoted_by_valid4096_shape(self):
        vector = [1 / math.sqrt(768)] * 768 + [0] * (4096 - 768)
        value = module.validate_vector_response(raw(self.vector_response(vector)), expected_token_count=3)
        self.assertFalse(value["production_allowed"])
        with self.assertRaises(module.LeanstralEmbeddingUnavailable):
            module.embed_rows([], owner_verifier={"dimension": 4096, "validated": True, **value})

    def test_vector_protocol_rejects_wrong_width_zero_nonfinite_and_boolean_values(self):
        for vector in ([1] * 768, [1] * 4095, [0] * 4096, [True] * 4096,
                       [float("nan")] + [0] * 4095, [float("inf")] + [0] * 4095,
                       [10**400] + [0] * 4095):
            encoded = json.dumps(self.vector_response(vector), allow_nan=True).encode()
            with self.assertRaises(ValueError): module.validate_vector_response(encoded, expected_token_count=3)

    def test_embedding_token_accounting_model_order_and_extra_fields_are_closed(self):
        for mutation in (lambda v: v["usage"].update(prompt_tokens=2),
                         lambda v: v["usage"].update(total_tokens=True),
                         lambda v: v.update(model="other"), lambda v: v["data"][0].update(index=True),
                         lambda v: v["data"][0].update(truncated=True),
                         lambda v: v["data"].append(v["data"][0])):
            value = self.vector_response([1 / 64] * 4096); mutation(value)
            with self.assertRaises(ValueError): module.validate_vector_response(raw(value), expected_token_count=3)

    def test_witness_requirements_are_descriptive_and_caller_json_or_boolean_cannot_authorize(self):
        requirements = module.NativeOwnerVerificationRequirements().to_dict()
        self.assertFalse(requirements["caller_json_is_witness"])
        self.assertFalse(requirements["persistent_freshness_token"])
        for field in ("service_process_birth", "operation_seal", "native_output_dimension", "entry_callback", "closing_callback"):
            self.assertIn(field, requirements["required_fields"])
        with patch.object(module.urllib.request, "build_opener") as opened:
            for witness in (True, {"verified": True}, requirements, lambda: True):
                with self.assertRaises(module.LeanstralEmbeddingUnavailable): module.embed_rows([], owner_verifier=witness)
            opened.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
