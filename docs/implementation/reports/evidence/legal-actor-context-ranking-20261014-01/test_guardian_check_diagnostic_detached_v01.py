"""Synthetic stderr labels and static fixed-child checks; never runs the producer."""
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import unittest

F = Path(__file__).resolve().parent
SOURCE = F / 'diagnose_actor_context_ranking_guardian_check_v01.py'
OUTPUT = F / 'guardian-check-diagnostic-author-controls-v01.json'


def pin(path):
    b = path.read_bytes()
    return dict(path=str(path), bytes=len(b), sha256=hashlib.sha256(b).hexdigest())


TREE = ast.parse(SOURCE.read_text())
selected = [node for node in TREE.body if isinstance(node, ast.FunctionDef) and node.name == 'classify'
            or isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in ('SAFE_MESSAGES', 'SAFE_CLASSES') for t in node.targets)]
NAMESPACE = dict(re=re)
exec(compile(ast.Module(body=selected, type_ignores=[]), '<detached-classifier>', 'exec'), NAMESPACE)
classify = NAMESPACE['classify']


class Controls(unittest.TestCase):
    def label(self, value, **kw):
        return classify(value, **dict(returncode=1, timed_out=False, output_bounded=True, **kw))

    def test_exact_known_message(self):
        v = self.label(b'Traceback (most recent call last):\nValueError: closed existing scheduler state inventory required\n')
        self.assertEqual(v, dict(exception_class='ValueError', message='closed existing scheduler state inventory required', exact_allowlisted_message=True))

    def test_private_unknown_value_redacted(self):
        v = self.label(b'ValueError: secret claim body /private/path TOKEN=xyz\n')
        self.assertEqual(v['message'], 'Details retained in private stderr.')
        self.assertFalse(v['exact_allowlisted_message'])

    def test_module_path_redacted(self):
        self.assertEqual(self.label(b"ModuleNotFoundError: No module named 'private.name'\n")['message'], 'Details retained in private stderr.')

    def test_missing_path_redacted(self):
        self.assertEqual(self.label(b"FileNotFoundError: [Errno 2] /private/ledger\n")['message'], 'Details retained in private stderr.')

    def test_dynamic_key_redacted(self):
        self.assertFalse(self.label(b'ValueError: integer scheduler field required: private_key\n')['exact_allowlisted_message'])

    def test_namespaced_class_only(self):
        self.assertEqual(self.label(b'private.module.ResourceConfigurationError: opaque\n')['exception_class'], 'ResourceConfigurationError')

    def test_unknown_class_redacted(self):
        self.assertEqual(self.label(b'PrivateException: confidential\n')['exception_class'], 'Unclassified')

    def test_non_utf8_does_not_leak(self):
        self.assertEqual(self.label(b'ValueError: \xff\xfe\n')['message'], 'Details retained in private stderr.')

    def test_timeout_is_fixed(self):
        self.assertEqual(classify(b'secret', returncode=None, timed_out=True, output_bounded=True)['exception_class'], 'TimeoutError')

    def test_unbounded_is_fixed(self):
        self.assertEqual(classify(b'ValueError: closed existing scheduler state inventory required', returncode=1, timed_out=False, output_bounded=False)['exception_class'], 'Unclassified')

    def test_success_does_not_claim_admission(self):
        self.assertIn('not an admission proof', classify(b'secret', returncode=0, timed_out=False, output_bounded=True)['message'])

    def test_fixed_one_child_call(self):
        calls = [n for n in ast.walk(TREE) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and isinstance(n.func.value, ast.Name) and n.func.value.id == 'subprocess']
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].func.attr, 'run')
        self.assertEqual(ast.unparse(calls[0].args[0]), "[sys.executable, '-B', str(GUARDIAN), '--check']")
        self.assertEqual(next(k.value.value for k in calls[0].keywords if k.arg == 'timeout'), 15)
        self.assertFalse(any(isinstance(n, (ast.For, ast.While)) and any(c is calls[0] for c in ast.walk(n)) for n in ast.walk(TREE)))


if __name__ == '__main__':
    before = pin(SOURCE)
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Controls)
    result = unittest.TestResult()
    suite.run(result)
    assert result.wasSuccessful(), 'synthetic diagnostic controls failed'
    assert pin(SOURCE) == before, 'diagnostic source changed'
    receipt = dict(schema='actor-context-ranking-guardian-check-diagnostic-author-controls/v1',
                   passed=True, findings=[], tests_run=result.testsRun, failures=len(result.failures), errors=len(result.errors),
                   producer=before, controls_source=pin(Path(__file__).resolve()), independent_qualification=False,
                   actual_guardian_calls=0, endpoint_body_reads=0, actual_model_calls=0, subprocess_calls=0,
                   producer_main_executed=False, synthetic_classifier_and_AST_only=True)
    with OUTPUT.open('x') as stream:
        json.dump(receipt, stream, sort_keys=True, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    OUTPUT.chmod(0o444)
    print(json.dumps(pin(OUTPUT), sort_keys=True))
