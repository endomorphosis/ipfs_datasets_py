"""Prepare saved native parser views; execute no models, compiler or subprocesses.

This helper deliberately omits shared-scope and statutory-preflight runtime.
It prepares twelve bounded parser requests, retaining all twenty-four declared
attempts and all sixteen exposed-law dispositions. No registered temporal/event
family, legal accuracy, authenticated model or review, or admission is claimed.
Run only after independent review of this frozen helper and its source owners.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys

from bootstrap_inert import install, ROOT, PACKAGES

F = Path(__file__).resolve().parent
PARENT = F.parent / "legal-formal-output-20261011-01"
R = Path("/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/legal-trigger-readout-pilot-20261007-01/structured-probability-20261011-01/results")
OUT = F / "prepared-native-views-v02"
CHECKPOINT_CANONICAL_SHA256 = "89ba30be1de11b6f9f52263138a41cbc286a1c9bd48981801ab54ff7b11a9630"
TOOLCHAIN = "leanprover/lean4:v4.34.1"
PROFILES = ("tdfol", "dcec")
DENIED_NUMERICAL_ROOTS = {"torch", "numpy", "transformers", "sentence_transformers", "tensorflow", "jax"}
MAX_JSON_BYTES = 32 * 1024**2

# These are external file identities, distinct from owners' canonical content
# digests. The checkpoint is SHA-checked as bytes only, never JSON-decoded.
FROZEN_INPUTS = {
    "development_source": (F / "authored-development-source-only-v02.json", 4968, "34fe6b7255c89292c148e79070f657104ba8a7855f44d936168309246bd31e5d"),
    "development_declarations": (F / "authored-development-cue-declarations-v02.json", 9753, "67b80ed4224b3d04f636d980dd66b323ca6c1786fc058407782b8f13a7170756"),
    "statutory_source": (F / "statutory-source-only-inputs.json", 4311, "8e32b64579eb67b604d7ba7cd907d17da7c8934e354b0641cd344b6522049fc3"),
    "bootstrap": (F / "bootstrap_inert.py", 1208, "030ac4f55adf5bf305bab0fcef9e33daa27c8fd083ddd474eac623e754246da1"),
    "original_full_tuning_report": (R / "source_only-1729-ce0-tuning-greedy.json", 874913, "5a127645d451907b79a7cdca4ab64f61f4c0f0ec181ea31e1e101a4aa97907d8"),
    "original_checkpoint_file": (R / "source_only-1729-ce0-checkpoint.json", 4117352, "89ba30be1de11b6f9f52263138a41cbc286a1c9bd48981801ab54ff7b11a9630"),
    "original_statutory_raw_report": (R / "source_only-1729-ce0-law-none.json", 274731, "b9ec06cb84136161a167b243775f5428f607cbb7d770a4c53a4cf59da88ae710"),
    "original_statutory_joint_report": (R / "source_only-1729-ce0-law-none-joint.json", 103504, "7ee549b131396a70dedcda7550e3ed5a3e32d6910c3118940a82dcf53847599a"),
    "prior_preparation_summary": (PARENT / "prepared-pilot-v01/preparation-summary.json", 64357, "82fcae238ba6e87d6eb44f97ee0b0da91ead6c1ba35367b7a695b2d7d99f879b"),
    "prior_empty_review_preflight": (PARENT / "prepared-pilot-v01/actual-statutory-preflight.json", 47619, "d7488d74d6418d61992e840bf26bc4ec9140ba704eb39e244e45761b8775a1fd"),
    "prior_empty_review_replay": (PARENT / "prepared-pilot-v01/actual-statutory-preflight-replay.json", 1997, "018196a7576181f78a9891b122e299fc1059a1723d121156dcef259126775644"),
    "old_source_owner_ledger": (PARENT / "retained-owner-pins.json", 19233, "331302c6dedeb21980062be387e92e2cac9c88bd7b8f78b4a8f7250e49af6305"),
    "new_native_view_source": (ROOT / "ipfs_datasets_py/logic/legal_ir/saved_span_native_views.py", 13297, "049260f3a683d58a906290436667804f410d4839161cfe7e2202b37b7f892d6d"),
    "new_native_view_tests": (ROOT / "tests/unit/logic/legal_ir/test_saved_span_native_views.py", 29921, "6fa7b07bd5f3bfc3c750f65cb99917cdfaa07bd370e2321529775ad338707a90"),
    'preserved_failed_preparation_helper': (F / 'prepare_scope_native_pilot.py', 29975, 'f07a2e4ddce24660eab76798fc81dc6502fb5d0f089bc809ac6b3e7e8e7145e4'),
    'preserved_failed_preparation_build_receipt': (F / 'prep-helper-build-v01.json', 11428, '561ce05b5ee5d3b5c177afd5979a05f7e2c70f9f873472c4064d9be0e4674cc2'),
    'preserved_failed_preparation_log': (F / 'preparation-execution-v01.log', 603, '6574a8e58c8cfd193afcb91f81366a45154dd6006420f2f052ecf2b55fb4a87a'),
}

# Exact committed strict-DCEC import closure, omitted from the older
# deontic-only loaded producer map. Unknown runtime modules still fail closed.
ADDITIONAL_DCEC_SOURCE_ENDPOINTS = {
    "ipfs_datasets_py.logic.families.namespaces": {
        "bytes": 34262,
        "relative_path": "ipfs_datasets_py/logic/families/namespaces.py",
        "sha256": "ba097e653158a812d66ead978d6405d61adaa293521305333579b19bd69a432d"
    },
    "ipfs_datasets_py.logic.parsers": {
        "bytes": 8980,
        "relative_path": "ipfs_datasets_py/logic/parsers/__init__.py",
        "sha256": "e75f0c2ffea0f0706a3d1768a794849e6c013b6647dc59ba331f44797c233386"
    },
    "ipfs_datasets_py.logic.parsers.event_calculus": {
        "bytes": 59003,
        "relative_path": "ipfs_datasets_py/logic/parsers/event_calculus.py",
        "sha256": "8bd7217febef6daf86f76bae7e03ab0cbf7eb22a1b64f3040fd26a3d2ebfc390"
    },
    "ipfs_datasets_py.logic.parsers.legacy_modal": {
        "bytes": 71642,
        "relative_path": "ipfs_datasets_py/logic/parsers/legacy_modal.py",
        "sha256": "7b18812ea6fcba8b65ed7dc5c3407e0ad06ac9760c5c66441e9677463f9eb66e"
    },
    "ipfs_datasets_py.logic.parsers.modal": {
        "bytes": 99829,
        "relative_path": "ipfs_datasets_py/logic/parsers/modal.py",
        "sha256": "3131ff1dd516ebdf52071215c2c7983f9cf317d86bb138ff9437faae9b227942"
    },
    "ipfs_datasets_py.logic.syntax_core": {
        "bytes": 8285,
        "relative_path": "ipfs_datasets_py/logic/syntax_core/__init__.py",
        "sha256": "20dd418d90360cdb42c64ba8b87bedcdb640228b460ef6c6ae60312365130e81"
    },
    "ipfs_datasets_py.logic.syntax_core.algebra": {
        "bytes": 45735,
        "relative_path": "ipfs_datasets_py/logic/syntax_core/algebra.py",
        "sha256": "d3587e2270943167ebef226e03cbd70cfc8888d936647670a21cfa514240e6b7"
    },
    "ipfs_datasets_py.logic.syntax_core.ast": {
        "bytes": 56966,
        "relative_path": "ipfs_datasets_py/logic/syntax_core/ast.py",
        "sha256": "4709513f18ab270858fe9595d88a847ddc52092606c52c7802947abed1ab9ac4"
    },
    "ipfs_datasets_py.logic.syntax_core.contracts": {
        "bytes": 75291,
        "relative_path": "ipfs_datasets_py/logic/syntax_core/contracts.py",
        "sha256": "ce6d49e05ca2b09a84a3125ed6ad4c4aae4adf2c5943d3a4fd4eeeb057b444a8"
    },
    "ipfs_datasets_py.logic.syntax_core.diagnostics": {
        "bytes": 10752,
        "relative_path": "ipfs_datasets_py/logic/syntax_core/diagnostics.py",
        "sha256": "a291db3c2cea04ae8dd9221a5e5ddbebd419679c02a5a008034e3755e7650d8f"
    },
    "ipfs_datasets_py.logic.syntax_core.lexer": {
        "bytes": 27534,
        "relative_path": "ipfs_datasets_py/logic/syntax_core/lexer.py",
        "sha256": "f666e9759323508f4e90964c0d71164645af9ce1de60bed778e5f64f7f4a3aea"
    },
    "ipfs_datasets_py.logic.syntax_core.registry": {
        "bytes": 27560,
        "relative_path": "ipfs_datasets_py/logic/syntax_core/registry.py",
        "sha256": "eff5ca12d748eff1e9463b737a8243c97d89cac51e1b604fe2c765aed885cb44"
    },
    "ipfs_datasets_py.logic.syntax_core.signatures": {
        "bytes": 30488,
        "relative_path": "ipfs_datasets_py/logic/syntax_core/signatures.py",
        "sha256": "49dd4fb0096661a05a15f056eb57248349e2b4e0b02e83239f36db36788c75bf"
    }
}

# Preserve every body from the fail-closed first preparation attempt.
PRESERVED_FAILED_OUTPUTS = {
    "all-or-none-unsupported-batch.json": {
        "bytes": 18916,
        "sha256": "410769ae6c5c558e706418203f6c7ef7ba296ffb9c7356e79b3dca5a8e258176"
    },
    "development-attempts.json": {
        "bytes": 26044,
        "sha256": "f093830c792dacc391b14a82e4ca1d947735e3014e43d5df4a737c91fcc57feb"
    },
    "development-packet-declarations.json": {
        "bytes": 6546,
        "sha256": "8263dd27408fbafa01e75fdce0cb9560a7ba9502cf2ea5998c8259dc2405e2cf"
    },
    "development/00-dcec-native-view.json": {
        "bytes": 66222,
        "sha256": "b3a2667d5392bf94288a8407f4025a2e2896216772768622043d3d1f70efe230"
    },
    "development/00-declaration.json": {
        "bytes": 1325,
        "sha256": "72d7485018c8d34c227041eedf7ac110d7d83c630ca5decd200744326937b4b2"
    },
    "development/00-pending.json": {
        "bytes": 934260,
        "sha256": "273ffdefae7a56bb4dd18b37780e57274efc04818970746d8dea31a95e6c84c2"
    },
    "development/00-tdfol-native-view.json": {
        "bytes": 58465,
        "sha256": "230b352215bb8c3854fce6c6d0cfe9fb047f9c62ca381dd0994539011cbc318b"
    },
    "development/01-dcec-native-view.json": {
        "bytes": 66202,
        "sha256": "72fbe9878d2b566b7c3994a9f3a8645793f4ae934c4c8980dc3049f53fb0c536"
    },
    "development/01-declaration.json": {
        "bytes": 1321,
        "sha256": "3fad4be103f9925f35f07f0074467d26b82eece0571042583d78a0837839561e"
    },
    "development/01-pending.json": {
        "bytes": 934256,
        "sha256": "5557517bc22f86a8513cf4b58431bc09d5d77a922dc53e47b71c603db51abbbf"
    },
    "development/01-tdfol-native-view.json": {
        "bytes": 58445,
        "sha256": "ee0f36a06735c2cabdc5cb23256833e020eef16c8b3f5c84c28875fce64d9389"
    },
    "development/02-dcec-native-view.json": {
        "bytes": 66392,
        "sha256": "505fa9cd1e16d73d7146cbb204e977abf499177e762a035add1e0d728c20ee8f"
    },
    "development/02-declaration.json": {
        "bytes": 1333,
        "sha256": "c5d227326e7c245c080f1bd9bc750a765eb0f66f20fa9c3a7c21dd30cec6f836"
    },
    "development/02-pending.json": {
        "bytes": 934268,
        "sha256": "f43ee8efe0119d296fc21ecdc0635ce4d0da89b83505504694363daa84121d6b"
    },
    "development/02-tdfol-native-view.json": {
        "bytes": 58505,
        "sha256": "cea13e812a36885ace36f2813d2b6ace319fc7f8bf6512ee8723356ce60b81c3"
    },
    "development/03-declaration.json": {
        "bytes": 1746,
        "sha256": "4e66f8a5c113950b4dfe7e4f4787d9eb3a7a53e274d7c21fb616ca3919451bc2"
    },
    "development/03-pending.json": {
        "bytes": 934780,
        "sha256": "c4b381a9e719dcc1a490f0ab81141aa99f2f8f17e7e47d5d6d09cca19b9590da"
    },
    "development/03-tdfol-native-view.json": {
        "bytes": 68559,
        "sha256": "38e6893ea2f38abe06e59030a94d70aa8d9886b219ed4cb1c7770ba1fdccdec1"
    },
    "development/04-declaration.json": {
        "bytes": 1764,
        "sha256": "683033d9e501d5fb2f2bab9592427bcd4151f58ead7a739662571ae22f61734f"
    },
    "development/04-pending.json": {
        "bytes": 934799,
        "sha256": "bc6badd5071910f298b6159a52c22b120313a850749f1e85f5e61c5c27d60c10"
    },
    "development/04-tdfol-native-view.json": {
        "bytes": 68649,
        "sha256": "8fa708f7fe51587ebf08cc825507b60cfcbeeba3b3999f4164b1465287a38005"
    },
    "development/05-declaration.json": {
        "bytes": 1754,
        "sha256": "593b03fbee841370dd383b9ea0f37bf4a120ce6296b71c8c4eae0c4a50b768ed"
    },
    "development/05-pending.json": {
        "bytes": 934788,
        "sha256": "cf33a17b35d9457751383dd7312e9ec7ad3e548ae3d4569951fe839c6f002002"
    },
    "development/05-tdfol-native-view.json": {
        "bytes": 68599,
        "sha256": "e2fdd4cd773e0d5a450241c83d4ff62b47cb459d0996c66cd3035f6bd04f67b7"
    },
    "development/06-declaration.json": {
        "bytes": 1788,
        "sha256": "b6bbf2ac7b13fe4886dc84e15fcfbced10e27807894eb0b065147244bfa26517"
    },
    "development/06-pending.json": {
        "bytes": 934837,
        "sha256": "807363fd072fcb117133764eedda5bbeeeca4bc73229ec0551e2befca1f51ace"
    },
    "development/06-tdfol-native-view.json": {
        "bytes": 69953,
        "sha256": "eddb97427641490db8962916d992a9a15c94e18c00668dda491ef9fcd60a66b9"
    },
    "development/07-declaration.json": {
        "bytes": 1796,
        "sha256": "417f6d37dd614f5157c4426b516958ead9b1a89892e3521c2f6ebb7b6e28b74a"
    },
    "development/07-pending.json": {
        "bytes": 934845,
        "sha256": "d6a484831efe64a45cd682b677fcf81fe554301f9afe54de82747ab3be196832"
    },
    "development/07-tdfol-native-view.json": {
        "bytes": 69993,
        "sha256": "7c3929936d8ac47283e84b90ffddc4c192518d238a0eab25fc779174886c4b86"
    },
    "development/08-declaration.json": {
        "bytes": 1792,
        "sha256": "4b46342749a57f10067aa69e7fb23707b57feb41bdae0e90fab4fd778fb01c58"
    },
    "development/08-pending.json": {
        "bytes": 934841,
        "sha256": "087306623e6841ec92a2225e3c200f7489688477e975aa24e17d2b872ea4b211"
    },
    "development/08-tdfol-native-view.json": {
        "bytes": 69973,
        "sha256": "15e1b7c10c01ff5c56aa0972a447f79547ecae679b58d142b3a4f73386f8ada8"
    },
    "expected-native-modules.json": {
        "bytes": 501,
        "sha256": "9da7db9df58992b6139e43c61f7b550609afd8231900408c139d686e0487597e"
    },
    "native-negative-controls.json": {
        "bytes": 2867,
        "sha256": "21445dcf998cf28352919847fc92bf6cc46253e6612e295b59d05717c5ac10d1"
    },
    "native-preparation-manifest.json": {
        "bytes": 19836,
        "sha256": "94297c54dc8fef65c7049f422b4ba6e7821a95e6dd9bf2e4e11250354fbaffa1"
    },
    "native-prepared/LegalSourceFamily.lean": {
        "bytes": 468,
        "sha256": "e5da88c4fc54e8931ed244e2b461cf43800f47af316f043532072d161de6a0f0"
    },
    "native-prepared/LegalSourceFamily/Candidate0000.lean": {
        "bytes": 539,
        "sha256": "5ea88c69f307e7832190e2d24ed3fb46d78944a12686a11ebd15dd4dc914aab6"
    },
    "native-prepared/LegalSourceFamily/Candidate0001.lean": {
        "bytes": 533,
        "sha256": "692ad74f34b39449e35b40d1af3ce28b095b82d96497da4e9324537895e546b2"
    },
    "native-prepared/LegalSourceFamily/Candidate0002.lean": {
        "bytes": 539,
        "sha256": "791a4e2df33121388349b7188ac321315563fc6708bf905d3aef9b66b347a54a"
    },
    "native-prepared/LegalSourceFamily/Candidate0003.lean": {
        "bytes": 533,
        "sha256": "6f0ef981e76e54d63beec0912e7aa6640b56281484a489851ef321b70be35df7"
    },
    "native-prepared/LegalSourceFamily/Candidate0004.lean": {
        "bytes": 539,
        "sha256": "6a4064cf9e54c9f9a5f777b5198e152cb1e35fa9df0197398dd3ca357893aaa5"
    },
    "native-prepared/LegalSourceFamily/Candidate0005.lean": {
        "bytes": 533,
        "sha256": "cf9be47d3d1bb5f1dfe2e04029e410f67cc80ee42905e6c1180250a0d0dfb799"
    },
    "native-prepared/LegalSourceFamily/Candidate0006.lean": {
        "bytes": 739,
        "sha256": "725516e0a512b8d1584af0e8cbc34d682375c882b14799eac596cffdb3cf43dd"
    },
    "native-prepared/LegalSourceFamily/Candidate0007.lean": {
        "bytes": 739,
        "sha256": "6727597bbbb89a7900e2c7c97a669bdf164349a2c0e1e84d2f40291f917fb529"
    },
    "native-prepared/LegalSourceFamily/Candidate0008.lean": {
        "bytes": 739,
        "sha256": "316168372b3b93c410f75640074bb122126582d0b42e691b9de6f88210572805"
    },
    "native-prepared/LegalSourceFamily/Candidate0009.lean": {
        "bytes": 757,
        "sha256": "568b7fa0a34a294d5f70a865eca2aba5e8bec64910f2ea6c66debae8ba775cb0"
    },
    "native-prepared/LegalSourceFamily/Candidate0010.lean": {
        "bytes": 757,
        "sha256": "eeb690e43b1452115b80090ff7b344df8a79c46b99ced1c6907bb92d0f406f1d"
    },
    "native-prepared/LegalSourceFamily/Candidate0011.lean": {
        "bytes": 757,
        "sha256": "c056dbc04010bc6a9007e6e5eb8e7e6a4c27a3ce9c4e8600a3e13dcb0d8d4cc8"
    },
    "native-prepared/LegalSourceFamily/Prelude.lean": {
        "bytes": 1270,
        "sha256": "e9272074805daf3e7329058cc1e10f59deece713e4f8ad04e9d123c37d3537ce"
    },
    "native-prepared/lakefile.toml": {
        "bytes": 106,
        "sha256": "357e3b2caacf63a7e9dafe4b0536b2ab68240327fdd7f20297ba2ae2fc6131c0"
    },
    "native-prepared/lean-toolchain": {
        "bytes": 25,
        "sha256": "d5edba4e4b8faad9c1baeadb265716d20d03be4d1a2647dc5e35b0c0325bea7b"
    },
    "native-prepared/source-family-inputs.json": {
        "bytes": 25733,
        "sha256": "f332ecd290990a57634998ae3faf73a8cc97ba230656472f46621855eb7fe848"
    },
    "native-requests.json": {
        "bytes": 37398,
        "sha256": "9d356da73384d96d586c028cd69f4533866201d95ce70489bce0767c4b0d50f5"
    },
    "prior-empty-review-metadata.json": {
        "bytes": 1017,
        "sha256": "36317e809e161c71209e600d3fc60448f769d027c41ab392405a9cf62a2c67e0"
    },
    "statutory-dispositions.json": {
        "bytes": 12694,
        "sha256": "cf67a7ed82f49afa2d66dbf814dc7e04cc478544d217bbe05c6bb6b5ae5a638c"
    },
    "statutory/joint-00-blank-declaration.json": {
        "bytes": 1392,
        "sha256": "5f7c6d79befd5a21a8468be9a96d226b87bae453ff2843e7091bddef23de340e"
    },
    "statutory/joint-00-pending.json": {
        "bytes": 408036,
        "sha256": "019cec63449dadc23004c312b1da3fdc5d65b758656751a39ee17edd5a91a607"
    },
    "statutory/joint-01-blank-declaration.json": {
        "bytes": 1288,
        "sha256": "0847c2770690909415130e3ffb4709a832e436c7443b4b82777a41fddaba31d2"
    },
    "statutory/joint-01-pending.json": {
        "bytes": 407913,
        "sha256": "3a8af984e70ef22d93a456fc89ec433380f6aed77322b6aae26788cd5df5b345"
    },
    "statutory/joint-02-blank-declaration.json": {
        "bytes": 1262,
        "sha256": "e0a77f1f4449f8bf189343738cdc6f259b57a8818b3cb15e38d64981873cab26"
    },
    "statutory/joint-02-pending.json": {
        "bytes": 407835,
        "sha256": "b2df6ed4e111c58825edf1efb410ba2f4b92215637ea4fc57d6c061040319968"
    },
    "statutory/joint-05-blank-declaration.json": {
        "bytes": 1440,
        "sha256": "0a0fe3c935c8cade32a3b1d11e5a5b32cbc7536ee090c4e77c1981c077aa73f3"
    },
    "statutory/joint-05-pending.json": {
        "bytes": 408495,
        "sha256": "418578986e9370696bfdf54694e7cacab4b112872615ee9a813ad502f2e09f8d"
    },
    "statutory/raw-01-blank-declaration.json": {
        "bytes": 1288,
        "sha256": "b7afa935e79d55aba4f1321115a8fc84ca183001dde9f6e408029fb3b2d1e130"
    },
    "statutory/raw-01-pending.json": {
        "bytes": 298818,
        "sha256": "94632a56d4d3c90ff5f43a37aebd895e50e0e0c3883fb5d4934c07d2ad956020"
    }
}


def preserved_failed_endpoints():
    directory = F / "prepared-native-views-v01"
    actual = {str(path.relative_to(directory)): pin(path)
              for path in directory.rglob("*") if path.is_file()}
    assert set(actual) == set(PRESERVED_FAILED_OUTPUTS), "preserved failed preparation inventory changed"
    for relative, wanted in PRESERVED_FAILED_OUTPUTS.items():
        assert actual[relative] == {"path": str(directory / relative), **wanted}
    return actual


def pin(path):
    path = Path(path)
    assert path.is_absolute() and path.is_file() and not path.is_symlink() and path.resolve() == path, path
    raw = path.read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def expected_pin(spec):
    path, size, sha = spec
    return {"path": str(path), "bytes": size, "sha256": sha}


def read_json(path):
    raw = Path(path).read_bytes()
    assert 0 < len(raw) <= MAX_JSON_BYTES

    def pairs(items):
        result = {}
        for key, value in items:
            assert key not in result, "duplicate JSON key"
            result[key] = value
        return result

    def constant(value):
        raise ValueError("nonfinite JSON literal: " + value)

    result = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    json.dumps(result, allow_nan=False)
    return result


def output_path(name):
    relative = Path(name)
    assert not relative.is_absolute() and relative.parts and all(part not in (".", "..") for part in relative.parts)
    result = OUT / relative
    result.parent.mkdir(parents=True, exist_ok=True)
    assert result.parent.resolve() == result.parent and not result.parent.is_symlink()
    return result


def write_bytes(name, raw):
    assert type(raw) is bytes
    path = output_path(name)
    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    return pin(path)


def write_json(name, value):
    raw = (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    assert len(raw) <= MAX_JSON_BYTES
    return write_bytes(name, raw)


def audit(event, values):
    if event.startswith("socket.") or event.startswith("subprocess.") or event in {
        "os.system", "os.fork", "os.forkpty", "os.posix_spawn", "os.exec", "os.spawn", "pty.spawn"
    }:
        raise AssertionError("saved preparation cannot use network or external processes: " + event)
    if event == "import" and values and str(values[0]).split(".")[0] in DENIED_NUMERICAL_ROOTS:
        raise AssertionError("numerical backend prohibited: " + str(values[0]))


def must_refuse(case, call, needle=None):
    try:
        call()
    except ValueError as error:
        if needle is not None:
            assert needle in str(error), (case, str(error))
        return {"case": case, "refused": True, "reason": str(error),
                "model_calls": 0, "backend_calls": 0, "admitted": False}
    raise AssertionError("expected refusal: " + case)


def source_endpoints(prior_summary, old_ledger):
    """Rebind saved source byte identities to this isolated checkout, not old receipt bodies."""
    expected = {}
    prior_root = PARENT / "datasets"
    for name, old in dict(old_ledger, **prior_summary["loaded_producer_pins"]).items():
        old_path = Path(old["path"])
        relative = old_path.relative_to(prior_root)
        current = ROOT / relative
        wanted = {"path": str(current), "bytes": old["bytes"], "sha256": old["sha256"]}
        assert pin(current) == wanted, (name, current)
        expected[name] = wanted
    for name, spec in ADDITIONAL_DCEC_SOURCE_ENDPOINTS.items():
        assert name not in expected, ("unexpected existing DCEC mapping", name)
        current = ROOT / spec["relative_path"]
        wanted = {"path": str(current), "bytes": spec["bytes"], "sha256": spec["sha256"]}
        assert pin(current) == wanted, ("changed committed DCEC endpoint", name)
        expected[name] = wanted
    name = "ipfs_datasets_py.logic.legal_ir.saved_span_native_views"
    expected[name] = expected_pin(FROZEN_INPUTS["new_native_view_source"])
    return expected


def main():
    # Installation and producer imports occur only in this explicit reviewed
    # entry point. This authoring step does not invoke main.
    sys.addaudithook(audit)
    assert not (DENIED_NUMERICAL_ROOTS & set(sys.modules))
    input_pins = {name: pin(spec[0]) for name, spec in FROZEN_INPUTS.items()}
    assert all(input_pins[name] == expected_pin(spec) for name, spec in FROZEN_INPUTS.items())
    input_pins["preparation_helper"] = pin(Path(__file__).resolve())
    prior_summary = read_json(FROZEN_INPUTS["prior_preparation_summary"][0])
    old_ledger = read_json(FROZEN_INPUTS["old_source_owner_ledger"][0])
    assert len(old_ledger) == 62
    source_before = source_endpoints(prior_summary, old_ledger)
    failed_outputs_before = preserved_failed_endpoints()
    assert prior_summary["passed"] is True and prior_summary["source_only_dimension"] == 384
    assert prior_summary["source_only_latent_enabled"] is False
    assert prior_summary["checkpoint_canonical_sha256"] == CHECKPOINT_CANONICAL_SHA256
    state_file_pin = input_pins["original_checkpoint_file"]
    assert state_file_pin in prior_summary["input_pins"]
    checkpoint_binding = {
        "file_pin": state_file_pin, "canonical_sha256": CHECKPOINT_CANONICAL_SHA256,
        "configuration_metadata_receipt": input_pins["prior_preparation_summary"],
        "latent_dimension": 384, "latent_enabled": False,
        "current_file_byte_sha_verified": True, "checkpoint_JSON_decoded": False,
        "canonical_checkpoint_digest_recomputed": False, "tensors_loaded": False,
        "model_or_checkpoint_authenticated": False,
    }
    install()
    namespace_objects = {name: sys.modules[name] for name in PACKAGES}
    from ipfs_datasets_py.logic.legal_ir import saved_span_family_adapter as adapter
    from ipfs_datasets_py.logic.legal_ir import saved_span_native_views as views
    from ipfs_datasets_py.logic.autoformal import legal_source_family_bridge as bridge
    from ipfs_datasets_py.logic.autoformal import legal_source_family_lake as gate

    assert not OUT.exists()
    OUT.mkdir()
    inputs = read_json(FROZEN_INPUTS["development_source"][0])
    declarations = read_json(FROZEN_INPUTS["development_declarations"][0])
    raw = read_json(FROZEN_INPUTS["original_full_tuning_report"][0])
    assert inputs["parent_saved_inference_report"] == input_pins["original_full_tuning_report"]
    assert len(inputs["rows"]) == len(declarations["rows"]) == 12
    assert inputs["selected_original_positions"] == list(range(12))
    assert inputs["predeclared_native_positions"] == list(range(9))
    assert inputs["predeclared_temporal_refusal_positions"] == [9, 10, 11]
    assert inputs["semantic_gold"] is inputs["training_or_evaluation_admission"] is False
    assert declarations["source_semantics_verified"] is declarations["training_or_evaluation_admission"] is False
    assert declarations["reviewer_authentication"] is False
    assert inputs["new_model_calls"] == 0 and inputs["latent_vectors_exported"] is False
    assert inputs["canonical_supervised_targets_exported"] is False
    assert len(raw["rows"]) == inputs["full_report_rows_preserved"] == 96
    assert raw["checkpoint_sha256"] == inputs["checkpoint_canonical_sha256"] == CHECKPOINT_CANONICAL_SHA256
    raw_digest = adapter.digest(raw)
    requests, attempts, eligible_rows, positive = [], [], [], []
    for source, supplied in zip(inputs["rows"], declarations["rows"], strict=True):
        position = supplied["position"]
        assert type(position) is int and 0 <= position < 12
        assert source["id"] == supplied["id"] == raw["rows"][position]["id"]
        assert source["source_sha256"] == raw["rows"][position]["source_sha256"]
        assert supplied["modality_span"]["canonical_value"] == raw["rows"][position]["decoder_row"]["canonical_ir"]["rules"][0]["modality"]

        def pending():
            return adapter.prepare_pending(source, raw, expected_report_sha256=raw_digest,
                expected_checkpoint_sha256=CHECKPOINT_CANONICAL_SHA256, row_id=source["id"])

        if supplied["expected_bounded_profile_outcome"] == "temporal_refused":
            assert position in (9, 10, 11)
            refusal = must_refuse("unchanged_temporal_pending_profile", pending, "temporal")
            for profile in PROFILES:
                attempts.append({"id": source["id"], "original_position": position,
                    "native_parser_profile": profile, "status": "temporal_profile_refused",
                    "attempt_stage": "unchanged_pending_preparation", "native_view_API_called": False,
                    "refusal": deepcopy(refusal), "semantic_accuracy": None, "admitted": False})
            continue
        assert supplied["expected_bounded_profile_outcome"] == "native" and position < 9
        packet = pending()
        seal = adapter.digest(packet)
        assert adapter.validate_pending(packet, expected_packet_sha256=seal)
        declaration = adapter.declaration_skeleton(packet)
        declaration["occurrence"].update(occurrence_id=supplied["occurrence_id"],
            start_char=supplied["start_char"], end_char=supplied["end_char"], source_text=source["source_text"],
            modality_anchor=deepcopy(supplied["modality_span"]))
        interpretation = declaration["interpretation"]
        interpretation.update(activation_scope=bridge.ACTIVATION_SCOPE, exception_scope=bridge.EXCEPTION_SCOPE)
        for facet in ("conditions", "exceptions"):
            supplied_rows = supplied["qualifier_interpretations"][facet]
            assert [row["literal"] for row in supplied_rows] == [row["literal"] for row in interpretation["rules"][0][facet]]
            interpretation["rules"][0][facet] = deepcopy(supplied_rows)
        saved_pins = [write_json(f"development/{position:02d}-pending.json", packet),
                      write_json(f"development/{position:02d}-declaration.json", declaration)]
        eligible_rows.append({"id": source["id"], "original_position": position,
                              "packet_sha256": seal, "outputs": saved_pins})
        for profile in PROFILES:
            if profile == "dcec" and position >= 3:
                refusal = must_refuse("DCEC_qualifier_refusal", lambda: views.prepare_native_view(packet, declaration,
                    expected_packet_sha256=seal, native_parser_profile=profile), "qualifier-free")
                attempts.append({"id": source["id"], "original_position": position,
                    "native_parser_profile": profile, "status": "qualified_DCEC_profile_refused",
                    "attempt_stage": "native_view_preparation", "native_view_API_called": True,
                    "refusal": refusal, "packet_sha256": seal, "outputs": deepcopy(saved_pins),
                    "semantic_accuracy": None, "admitted": False})
                continue
            result = views.prepare_native_view(packet, declaration, expected_packet_sha256=seal,
                                               native_parser_profile=profile)
            assert views.validate_native_view(result, packet, declaration, expected_packet_sha256=seal,
                                              native_parser_profile=profile)
            assert result["sealed_legal_family"] == result["sealed_route"]["family_id"] == "deontic"
            assert result["canonical_ir"] == raw["rows"][position]["decoder_row"]["canonical_ir"]
            assert all(result[key] is False for key in views.FALSE)
            request = deepcopy(result["request"])
            request["family"] = profile
            requests.append(request)
            positive.append((position, packet, declaration, result))
            result_pin = write_json(f"development/{position:02d}-{profile}-native-view.json", result)
            attempts.append({"id": source["id"], "original_position": position,
                "native_parser_profile": profile, "status": "native_parser_view_prepared",
                "attempt_stage": "native_view_preparation", "native_view_API_called": True,
                "packet_sha256": seal, "outputs": [*deepcopy(saved_pins), result_pin],
                "registry_family_qualified": False, "sealed_legal_family": "deontic",
                "semantic_accuracy": None, "admitted": False})
    assert len(attempts) == 24 and len(eligible_rows) == 9 and len(requests) == len(positive) == 12
    assert [(row["original_position"], row["native_parser_profile"]) for row in attempts] == [
        (position, profile) for position in range(12) for profile in PROFILES]
    assert sum(row["status"] == "temporal_profile_refused" for row in attempts) == 6
    assert sum(row["status"] == "qualified_DCEC_profile_refused" for row in attempts) == 6
    assert sum(request["family"] == "tdfol" for request in requests) == 9
    assert sum(request["family"] == "dcec" for request in requests) == 3
    write_json("development-attempts.json", attempts)
    write_json("development-packet-declarations.json", eligible_rows)

    negative = []
    _, packet, declaration, result = positive[0]
    seal = adapter.digest(packet)
    for profile in ("TDFOL", "event_calculus", "fol", "deontic_fol"):
        negative.append(must_refuse("native_parser_alias_" + profile, lambda profile=profile:
            views.prepare_native_view(packet, declaration, expected_packet_sha256=seal,
                                      native_parser_profile=profile), "native_parser_profile"))
    bad = deepcopy(declaration)
    bad["occurrence"]["modality_anchor"]["end_char"] += 1
    negative.append(must_refuse("wrong_modality_literal", lambda: views.prepare_native_view(packet, bad,
        expected_packet_sha256=seal, native_parser_profile="tdfol"), "interval"))
    bad = deepcopy(declaration)
    span = packet["facet_geometry"]["actor"]
    bad["occurrence"]["modality_anchor"] = {key: span[key] for key in ("start_char", "end_char", "source_text")}
    bad["occurrence"]["modality_anchor"]["canonical_value"] = "O"
    negative.append(must_refuse("cue_overlaps_actor", lambda: views.prepare_native_view(packet, bad,
        expected_packet_sha256=seal, native_parser_profile="tdfol"), "overlaps"))
    bad = deepcopy(declaration)
    bad["interpretation"]["modal_context"] = "guessed_context"
    negative.append(must_refuse("nonnull_context", lambda: views.prepare_native_view(packet, bad,
        expected_packet_sha256=seal, native_parser_profile="tdfol")))
    for family in PROFILES:
        negative.append(must_refuse("unsupported_sealed_family_" + family, lambda family=family:
            adapter.prepare_family(packet, declaration, expected_packet_sha256=seal, family=family)))
    _, qpacket, qdeclaration, _ = next(row for row in positive if row[0] == 3)
    bad = deepcopy(qdeclaration)
    bad["interpretation"]["rules"][0]["conditions"][0]["expression"] = None
    negative.append(must_refuse("unfilled_qualifier_expression", lambda: views.prepare_native_view(qpacket, bad,
        expected_packet_sha256=adapter.digest(qpacket), native_parser_profile="tdfol")))
    for mutation in ("registry_qualification", "native_ast", "request"):
        changed = deepcopy(result)
        if mutation == "registry_qualification": changed["registry_family_qualified"] = True
        elif mutation == "native_ast": changed["native_view"]["formulas"][0]["native_ast"]["operator"]["value"] = "P"
        else: changed["request"]["occurrence_bindings"][0]["facets"]["actor"]["start_char"] += 1
        changed["output_sha256"] = views.digest({key: value for key, value in changed.items() if key != "output_sha256"})
        negative.append(must_refuse("resealed_output_" + mutation, lambda changed=changed:
            views.validate_native_view(changed, packet, declaration, expected_packet_sha256=seal,
                                       native_parser_profile="tdfol"), "replay"))
    assert len(negative) == 13
    write_json("native-negative-controls.json", negative)

    compiler = gate.prepare_source_family_legal(requests, toolchain=TOOLCHAIN)
    gate.validate_preparation(compiler)
    manifest = compiler.to_dict()
    assert manifest["all_candidates_supported"] is True and manifest["target"] == "legal"
    assert manifest["status"] == "prepared" and manifest["backend_executed"] is False
    assert len(manifest["candidates"]) == 12
    expected_modules = ["LegalSourceFamily.Prelude", *[row["module"] for row in manifest["candidates"]], "LegalSourceFamily"]
    assert len(expected_modules) == len(set(expected_modules)) == 14
    files = dict(compiler.files)
    assert len(files) == 17
    assert {name.replace("/", ".")[:-5] for name in files if name.endswith(".lean")} == set(expected_modules)
    write_json("native-requests.json", requests)
    write_json("native-preparation-manifest.json", manifest)
    write_json("expected-native-modules.json", expected_modules)
    for name, body in compiler.files:
        raw_body = body.encode("utf-8")
        assert hashlib.sha256(raw_body).hexdigest() == manifest["file_sha256"][name]
        write_bytes("native-prepared/" + name, raw_body)
    blocked_requests = deepcopy(requests) + [dict(deepcopy(requests[0]), family="fol")]
    blocked = gate.prepare_source_family_legal(blocked_requests, toolchain=TOOLCHAIN)
    gate.validate_preparation(blocked)
    blocked_manifest = blocked.to_dict()
    assert blocked_manifest["status"] == "blocked" and blocked_manifest["all_candidates_supported"] is False
    assert blocked_manifest["backend_executed"] is False and set(dict(blocked.files)) == {"source-family-inputs.json"}
    write_json("all-or-none-unsupported-batch.json", blocked_manifest)

    real = read_json(FROZEN_INPUTS["statutory_source"][0])
    real_raw = read_json(FROZEN_INPUTS["original_statutory_raw_report"][0])
    joint = read_json(FROZEN_INPUTS["original_statutory_joint_report"][0])
    assert len(real["rows"]) == len(real_raw["rows"]) == len(joint["rows"]) == 8
    assert real["semantic_gold"] is real["target_labels_exported"] is False
    assert real_raw["checkpoint_sha256"] == CHECKPOINT_CANONICAL_SHA256
    dispositions = []
    for lane in ("raw", "joint"):
        for position, source in enumerate(real["rows"]):
            options = {"joint_report": joint, "expected_joint_report_sha256": adapter.digest(joint)} if lane == "joint" else {}
            base = {"id": source["id"], "position": position, "lane": lane,
                "original_saved_status": joint["rows"][position]["result"]["status"] if lane == "joint" else real_raw["rows"][position]["decoder_row"]["status"],
                "semantic_accuracy": None, "admitted": False, "declaration_filled": False,
                "compiler_executed": False, "registry_family_qualified": False}
            try:
                real_packet = adapter.prepare_pending(source, real_raw, expected_report_sha256=adapter.digest(real_raw),
                    expected_checkpoint_sha256=CHECKPOINT_CANONICAL_SHA256, row_id=source["id"], **options)
            except adapter.SavedSpanFamilyError as error:
                base.update(status="saved_proposal_or_profile_refused", reason=str(error))
            else:
                blank = adapter.declaration_skeleton(real_packet)
                real_seal = adapter.digest(real_packet)
                assert blank["occurrence"]["occurrence_id"] is None
                assert blank["occurrence"]["modality_anchor"]["start_char"] is None
                refusals = []
                for profile in PROFILES:
                    refusal = must_refuse("real_blank_declaration_" + profile, lambda profile=profile:
                        views.prepare_native_view(real_packet, blank, expected_packet_sha256=real_seal,
                                                  native_parser_profile=profile))
                    refusals.append({"native_parser_profile": profile, **refusal})
                base.update(status="pending_caller_declaration", blank_native_refusals=refusals,
                    outputs=[write_json(f"statutory/{lane}-{position:02d}-pending.json", real_packet),
                             write_json(f"statutory/{lane}-{position:02d}-blank-declaration.json", blank)])
            dispositions.append(base)
    assert len(dispositions) == 16
    assert sum(row["status"] == "pending_caller_declaration" for row in dispositions) == 5
    assert sum(row["status"] == "saved_proposal_or_profile_refused" for row in dispositions) == 11
    assert sum(len(row.get("blank_native_refusals", [])) for row in dispositions) == 10
    # Compare only source IDs, lane/order and dispositions, never old path-bearing
    # native reports or producer receipts from the prior isolated checkout.
    projection = lambda rows: [(row["id"], row["position"], row["lane"], row["status"], row.get("reason")) for row in rows]
    assert projection(dispositions) == projection(prior_summary["statutory_dispositions"])
    write_json("statutory-dispositions.json", dispositions)
    prior_review = read_json(FROZEN_INPUTS["prior_empty_review_preflight"][0])
    prior_replay = read_json(FROZEN_INPUTS["prior_empty_review_replay"][0])
    assert prior_review["status"] == "pending" and prior_review["item_count"] == 8
    assert prior_review["submission_count"] == prior_review["declaration_count"] == prior_review["gold_labels_created"] == 0
    assert all(type(value) is int and value == 0 for value in prior_review["admission_masks"].values())
    assert prior_replay["status"] == "validated_declared_preflight_only"
    assert prior_replay["admission_masks"] == prior_review["admission_masks"]
    review_metadata = {"scope": "Pinned prior empty review evidence only; this helper does not replay or create reviews/preflight/scope declarations.",
        "actual_review_items": 8, "actual_human_submissions": 0, "actual_semantic_labels": 0,
        "admission_masks": deepcopy(prior_review["admission_masks"]), "current_preflight_executed": False,
        "current_scope_API_executed": False, "prior_preflight_pin": input_pins["prior_empty_review_preflight"],
        "prior_replay_pin": input_pins["prior_empty_review_replay"]}
    write_json("prior-empty-review-metadata.json", review_metadata)

    assert not (DENIED_NUMERICAL_ROOTS & set(sys.modules))
    loaded, namespaces = {}, {}
    for name in PACKAGES:
        assert sys.modules[name] is namespace_objects[name]
        assert getattr(namespace_objects[name], "__spec__", None) is None
        path = Path(namespace_objects[name].__file__).resolve()
        namespaces[name] = {"declaration": "synthetic namespace; file body not executed",
            "declared_path": str(path), "file_endpoint_pin": pin(path) if path.is_file() else None}
    for name, module in list(sys.modules.items()):
        if not name.startswith("ipfs_datasets_py.") or name in PACKAGES:
            continue
        path = getattr(module, "__file__", None)
        if path is not None:
            assert name in source_before, ("unfrozen producer", name, path)
            current = pin(Path(path).resolve())
            assert current == source_before[name], ("changed producer", name)
            loaded[name] = current
    assert "ipfs_datasets_py.logic.legal_ir.saved_span_native_views" in loaded
    assert set(ADDITIONAL_DCEC_SOURCE_ENDPOINTS) <= set(loaded), "declared DCEC closure not actually loaded"
    assert "ipfs_datasets_py.logic.legal_ir.statutory_declaration_preflight" not in loaded
    source_after = source_endpoints(prior_summary, old_ledger)
    assert source_before == source_after
    failed_outputs_after = preserved_failed_endpoints()
    assert failed_outputs_before == failed_outputs_after
    assert all(pin(spec[0]) == input_pins[name] for name, spec in FROZEN_INPUTS.items())
    assert pin(Path(__file__).resolve()) == input_pins["preparation_helper"]
    output_pins = [pin(path) for path in sorted(OUT.rglob("*")) if path.is_file()]
    summary = {"schema": "saved-span-native-parser-view-preparation-pilot/v1", "passed": True, "findings": [],
        "scope": "Saved source-only synthetic DEVELOPMENT predictions under explicit caller interpretations; exposed statutory proposals remain pending or refused.",
        "sealed_legal_family": "deontic", "registry_family_qualified": False,
        "parser_views_do_not_qualify_registered_families": True,
        "development_rows": 12, "development_requested": 12,
        "development_parser_attempts": 24, "development_outcomes": attempts,
        "eligible_packet_declaration_pairs": 9, "supported_parser_requests": 12,
        "native_requests_predeclared": 12,
        "TDFOL_ground_parser_requests": 9, "DCEC_qualifier_free_parser_requests": 3,
        "temporal_refused": 3, "temporal_refusal_attempts": 6, "DCEC_qualifier_refusal_attempts": 6,
        "full_original_report_rows": 96, "source_only_dimension": 384, "source_only_latent_enabled": False,
        "checkpoint_binding": checkpoint_binding,
        "expected_native_modules": expected_modules, "prepared_project_files": 17,
        "negative_controls": negative, "all_or_none_unsupported_batch_blocked": True,
        "statutory_dispositions": dispositions, "statutory_original_rows": 8, "statutory_lanes": 2,
        "statutory_pending_declarations": 5, "statutory_proposal_or_profile_refusals": 11,
        "statutory_blank_native_refusals": 10, "actual_review_metadata": review_metadata,
        "input_pins": [*input_pins.values(), *failed_outputs_before.values()], "frozen_input_pins_by_role": input_pins,
        "additional_committed_DCEC_source_endpoints": {name: source_before[name] for name in ADDITIONAL_DCEC_SOURCE_ENDPOINTS},
        "additional_DCEC_source_baseline": "7fc3f57a94108030be3cceca7368920754754a94",
        "prior_failed_preparation": {"passed": False, "stage": "loaded producer closure",
            "reason": "unfrozen producer ipfs_datasets_py.logic.syntax_core; prior deontic-only endpoint map omitted strict-DCEC shared parser dependencies",
            "output_count": 66, "outputs_preserved_before": failed_outputs_before, "outputs_preserved_after": failed_outputs_after,
            "old_helper_pin": input_pins["preserved_failed_preparation_helper"],
            "old_build_receipt_pin": input_pins["preserved_failed_preparation_build_receipt"],
            "failure_log_pin": input_pins["preserved_failed_preparation_log"],
            "model_calls": 0, "compiler_calls": 0, "source_owners_or_tests_changed": False},
        "source_endpoints_before": source_before, "source_endpoints_after": source_after,
        "loaded_producer_pins": loaded, "loaded_producer_endpoint_pins": loaded,
        "synthetic_namespace_endpoints": namespaces,
        "loaded_endpoint_scope": "Saved hashes of imported producer file endpoints, separate from synthetic namespace file endpoints; no continuous or authenticated execution provenance.",
        "output_pins": output_pins, "output_pins_excluding_summary_itself": output_pins,
        "model_calls": 0, "encoder_calls": 0, "optimizer_updates": 0,
        "compiler_executed": False, "preflight_runtime_executed": False, "scope_runtime_executed": False,
        "semantic_accuracy": None, "semantic_gold_created": False, "training_or_evaluation_admission": False,
        "proof_authority": False, "admitted": False, "cross_family_equivalence_verified": False,
        "cross_parser_AST_equality_asserted": False, "network_or_subprocess_calls": 0,
        "network_scope": "Python audit-hook denial of socket/process operations; no kernel network namespace claim.",
        "existing_native_gate_limits_unchanged": {"timeout_seconds": 60, "Lean_threads": 2,
            "sampled_tree_RSS_bytes": 2147483648, "max_workspace_bytes": 134217728,
            "max_output_bytes": 262144, "max_input_bytes": 8388608},
        "old_numerical_guardian_claims_or_caps_modified": False,
        "prior_deontic_build_scope": "The old nine deontic requests have a separate prior actual build; no old native receipts are regenerated or path-compared here.",
    }
    write_json("preparation-summary.json", summary)
    print("Prepared 12 parser requests / 14 expected modules; retained 24 attempts, 16 law dispositions and prior empty review evidence; no models or compiler calls.")


if __name__ == "__main__":
    main()
