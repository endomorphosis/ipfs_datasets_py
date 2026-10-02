namespace SecuritySourcePrograms

namespace Candidate_0
def sourceEvidenceOriginalProgramSHA256 : String := "d5a3022a6f0baecf5912927a3337dd8c306d7e7f04396c9dd19c8db55732999a"

def sourceEvidenceOperationalViewSHA256 : String := "7af8844c8e04d77e804ec74e19ec772741de37cd0790ff69683fb032758d06c1"

def sourceEvidenceSourceSHA256 : String := "764ed184dc7724aa170a38fb0a97856fdaebcf119d18bfaffcc28d60a69c194b"

def sourceEvidenceMetadataJSON : String := "{\"adapter\":\"SourceSoftwareVerificationAdapter@1\",\"assumptions\":[\"The annotation name int denotes exact built-in Python integers; annotations do not enforce runtime types.\",\"The mathematical integer model excludes resource exhaustion and concurrent environment changes.\",\"Native effects and purity retain the source adapter's conservative classification.\"],\"completion_authority\":false,\"effect_summary_assumption\":\"Read/write summaries are derived from the validated expression graph; all other effect flags and the native purity classification are preserved.\",\"effect_summary_audit\":{\"base_program_id\":\"bafkreiewp5e7kuwjq2w7v5n4k2loibjo2u6oaz7pdytj2znlgujnpk6nza\",\"base_program_sha256\":\"7e864b8aeacb2e290aed390a81167cc70900f5bddd6889bfdbca488073b8e116\",\"commands\":[{\"after\":{\"reads\":[\"symbol:calculate.capacity.parameter\",\"symbol:calculate.threshold.parameter\"],\"writes\":[]},\"before\":{\"reads\":[],\"writes\":[]},\"command_id\":\"command:11\",\"retained_effects\":{\"allocates\":[],\"deallocates\":[],\"nondeterministic\":false,\"performs_io\":false,\"raises\":[],\"synchronizes\":false}}],\"functions\":[{\"after\":{\"reads\":[\"symbol:calculate.capacity.parameter\",\"symbol:calculate.threshold.parameter\"],\"writes\":[]},\"before\":{\"reads\":[\"symbol:calculate.capacity.parameter\",\"symbol:calculate.threshold.parameter\"],\"writes\":[]},\"function_id\":\"function:calculate\",\"purity\":\"pure\",\"retained_effects\":{\"allocates\":[],\"deallocates\":[],\"nondeterministic\":false,\"performs_io\":false,\"raises\":[],\"synchronizes\":false}}],\"schema\":\"security-source-program-effect-audit/v1\"},\"effect_summary_contract\":\"closed-command-expression-reads-and-assignment-writes/v1\",\"execution_authority\":false,\"input_type_basis\":\"explicit_int_annotations\",\"language\":\"python\",\"path\":\"source.py\",\"proof_authority\":false,\"security_specification_inferred\":false,\"source_binding_effects_schema\":\"security-source-program-effects-384/v2\",\"source_binding_schema\":\"security-source-program-binding-384/v1\",\"source_semantics_verified\":false,\"source_sha256\":\"764ed184dc7724aa170a38fb0a97856fdaebcf119d18bfaffcc28d60a69c194b\",\"whole_program_semantics_verified\":false}"

def sourceEvidenceSourceReferencesJSON : String := "[{\"container_sha256\":\"\",\"container_uri\":\"\",\"content_cid\":\"\",\"content_sha256\":\"764ed184dc7724aa170a38fb0a97856fdaebcf119d18bfaffcc28d60a69c194b\",\"license_expression\":\"\",\"metadata\":{\"byte_length\":85,\"language\":\"python\",\"path\":\"source.py\"},\"ref_id\":\"source:source.py\",\"review_status\":\"unreviewed\",\"source_id\":\"source.py\",\"source_revision\":\"workspace:local\",\"source_uri\":\"file:///source.py\"}]"

def sourceEvidenceEffectAuditJSON : String := "{\"base_program_id\":\"bafkreiewp5e7kuwjq2w7v5n4k2loibjo2u6oaz7pdytj2znlgujnpk6nza\",\"base_program_sha256\":\"7e864b8aeacb2e290aed390a81167cc70900f5bddd6889bfdbca488073b8e116\",\"commands\":[{\"after\":{\"reads\":[\"symbol:calculate.capacity.parameter\",\"symbol:calculate.threshold.parameter\"],\"writes\":[]},\"before\":{\"reads\":[],\"writes\":[]},\"command_id\":\"command:11\",\"retained_effects\":{\"allocates\":[],\"deallocates\":[],\"nondeterministic\":false,\"performs_io\":false,\"raises\":[],\"synchronizes\":false}}],\"functions\":[{\"after\":{\"reads\":[\"symbol:calculate.capacity.parameter\",\"symbol:calculate.threshold.parameter\"],\"writes\":[]},\"before\":{\"reads\":[\"symbol:calculate.capacity.parameter\",\"symbol:calculate.threshold.parameter\"],\"writes\":[]},\"function_id\":\"function:calculate\",\"purity\":\"pure\",\"retained_effects\":{\"allocates\":[],\"deallocates\":[],\"nondeterministic\":false,\"performs_io\":false,\"raises\":[],\"synchronizes\":false}}],\"schema\":\"security-source-program-effect-audit/v1\"}"

def sourceEvidenceAssumptions : List String := ["The annotation name int denotes exact built-in Python integers; annotations do not enforce runtime types.", "The mathematical integer model excludes resource exhaustion and concurrent environment changes.", "Native effects and purity retain the source adapter's conservative classification.", "Read/write summaries are derived from the validated expression graph; all other effect flags and the native purity classification are preserved."]

def sourceEvidence_proof_authority : Bool := false

def sourceEvidence_execution_authority : Bool := false

def sourceEvidence_completion_authority : Bool := false

def sourceEvidence_source_semantics_verified : Bool := false

def sourceEvidence_whole_program_semantics_verified : Bool := false

def sourceEvidence_security_specification_inferred : Bool := false

def sourceEvidence_commands_reads : List (String × List String) := [("command:11", ["symbol:calculate.capacity.parameter", "symbol:calculate.threshold.parameter"])]

def sourceEvidence_commands_writes : List (String × List String) := [("command:11", [])]

def sourceEvidence_functions_reads : List (String × List String) := [("function:calculate", ["symbol:calculate.capacity.parameter", "symbol:calculate.threshold.parameter"])]

def sourceEvidence_functions_writes : List (String × List String) := [("function:calculate", [])]

set_option linter.unusedVariables false

structure Store where

  v0 : Int

  v1 : Int

  v2 : Int

  deriving DecidableEq



inductive Outcome where

  | returned (store : Store) (value : Int)

  | blocked

  | assertionFailure

  deriving DecidableEq

def expression_0 (initial current : Store) (returned : Int) : Int := (current.v0 + current.v2)

def expression_1 (initial current : Store) (returned : Int) : Int := current.v0

def expression_2 (initial current : Store) (returned : Int) : Int := current.v2

def run (initial : Store) : Outcome :=
  let current := initial;
  Outcome.returned current (expression_0 initial current (0 : Int))

def declaredReads (symbol : String) : Bool := ["symbol:calculate.capacity.parameter", "symbol:calculate.threshold.parameter"].contains symbol

example : (["symbol:calculate.capacity.parameter", "symbol:calculate.threshold.parameter"] : List String).all declaredReads = true := by decide

def declaredWrites (symbol : String) : Bool := [].contains symbol

example : ([] : List String).all declaredWrites = true := by decide
end Candidate_0

namespace Candidate_1
def sourceEvidenceOriginalProgramSHA256 : String := "d9a0a9d27c15fa03d222ef5f09535f0923a138cb889aa627baf905dc2735c39e"

def sourceEvidenceOperationalViewSHA256 : String := "0ac7eeb2e4f4a92dbf087ea84265afe36c95789bc01d1ca06e626e0bf8327ee8"

def sourceEvidenceSourceSHA256 : String := "181375e26822109916e3189665d6f031c99b73a456a1949e777c14992b3b1473"

def sourceEvidenceMetadataJSON : String := "{\"adapter\":\"SourceSoftwareVerificationAdapter@1\",\"assumptions\":[\"The annotation name int denotes exact built-in Python integers; annotations do not enforce runtime types.\",\"The mathematical integer model excludes resource exhaustion and concurrent environment changes.\",\"Native effects and purity retain the source adapter's conservative classification.\"],\"completion_authority\":false,\"effect_summary_assumption\":\"Read/write summaries are derived from the validated expression graph; all other effect flags and the native purity classification are preserved.\",\"effect_summary_audit\":{\"base_program_id\":\"bafkreigbjde2gzyavy3ts2t3jtwcayi7v4pp3mvt3ib6mlretxlju6afhu\",\"base_program_sha256\":\"1e72ce07b1e31b43f5ea535aa8f0c77102333e46a8a8296343073b05f30a261e\",\"commands\":[{\"after\":{\"reads\":[\"symbol:calculate.capacity.parameter\",\"symbol:calculate.threshold.parameter\"],\"writes\":[]},\"before\":{\"reads\":[],\"writes\":[]},\"command_id\":\"command:11\",\"retained_effects\":{\"allocates\":[],\"deallocates\":[],\"nondeterministic\":false,\"performs_io\":false,\"raises\":[],\"synchronizes\":false}}],\"functions\":[{\"after\":{\"reads\":[\"symbol:calculate.capacity.parameter\",\"symbol:calculate.threshold.parameter\"],\"writes\":[]},\"before\":{\"reads\":[\"symbol:calculate.capacity.parameter\",\"symbol:calculate.threshold.parameter\"],\"writes\":[]},\"function_id\":\"function:calculate\",\"purity\":\"pure\",\"retained_effects\":{\"allocates\":[],\"deallocates\":[],\"nondeterministic\":false,\"performs_io\":false,\"raises\":[],\"synchronizes\":false}}],\"schema\":\"security-source-program-effect-audit/v1\"},\"effect_summary_contract\":\"closed-command-expression-reads-and-assignment-writes/v1\",\"execution_authority\":false,\"input_type_basis\":\"explicit_int_annotations\",\"language\":\"python\",\"path\":\"source.py\",\"proof_authority\":false,\"security_specification_inferred\":false,\"source_binding_effects_schema\":\"security-source-program-effects-384/v2\",\"source_binding_schema\":\"security-source-program-binding-384/v1\",\"source_semantics_verified\":false,\"source_sha256\":\"181375e26822109916e3189665d6f031c99b73a456a1949e777c14992b3b1473\",\"whole_program_semantics_verified\":false}"

def sourceEvidenceSourceReferencesJSON : String := "[{\"container_sha256\":\"\",\"container_uri\":\"\",\"content_cid\":\"\",\"content_sha256\":\"181375e26822109916e3189665d6f031c99b73a456a1949e777c14992b3b1473\",\"license_expression\":\"\",\"metadata\":{\"byte_length\":85,\"language\":\"python\",\"path\":\"source.py\"},\"ref_id\":\"source:source.py\",\"review_status\":\"unreviewed\",\"source_id\":\"source.py\",\"source_revision\":\"workspace:local\",\"source_uri\":\"file:///source.py\"}]"

def sourceEvidenceEffectAuditJSON : String := "{\"base_program_id\":\"bafkreigbjde2gzyavy3ts2t3jtwcayi7v4pp3mvt3ib6mlretxlju6afhu\",\"base_program_sha256\":\"1e72ce07b1e31b43f5ea535aa8f0c77102333e46a8a8296343073b05f30a261e\",\"commands\":[{\"after\":{\"reads\":[\"symbol:calculate.capacity.parameter\",\"symbol:calculate.threshold.parameter\"],\"writes\":[]},\"before\":{\"reads\":[],\"writes\":[]},\"command_id\":\"command:11\",\"retained_effects\":{\"allocates\":[],\"deallocates\":[],\"nondeterministic\":false,\"performs_io\":false,\"raises\":[],\"synchronizes\":false}}],\"functions\":[{\"after\":{\"reads\":[\"symbol:calculate.capacity.parameter\",\"symbol:calculate.threshold.parameter\"],\"writes\":[]},\"before\":{\"reads\":[\"symbol:calculate.capacity.parameter\",\"symbol:calculate.threshold.parameter\"],\"writes\":[]},\"function_id\":\"function:calculate\",\"purity\":\"pure\",\"retained_effects\":{\"allocates\":[],\"deallocates\":[],\"nondeterministic\":false,\"performs_io\":false,\"raises\":[],\"synchronizes\":false}}],\"schema\":\"security-source-program-effect-audit/v1\"}"

def sourceEvidenceAssumptions : List String := ["The annotation name int denotes exact built-in Python integers; annotations do not enforce runtime types.", "The mathematical integer model excludes resource exhaustion and concurrent environment changes.", "Native effects and purity retain the source adapter's conservative classification.", "Read/write summaries are derived from the validated expression graph; all other effect flags and the native purity classification are preserved."]

def sourceEvidence_proof_authority : Bool := false

def sourceEvidence_execution_authority : Bool := false

def sourceEvidence_completion_authority : Bool := false

def sourceEvidence_source_semantics_verified : Bool := false

def sourceEvidence_whole_program_semantics_verified : Bool := false

def sourceEvidence_security_specification_inferred : Bool := false

def sourceEvidence_commands_reads : List (String × List String) := [("command:11", ["symbol:calculate.capacity.parameter", "symbol:calculate.threshold.parameter"])]

def sourceEvidence_commands_writes : List (String × List String) := [("command:11", [])]

def sourceEvidence_functions_reads : List (String × List String) := [("function:calculate", ["symbol:calculate.capacity.parameter", "symbol:calculate.threshold.parameter"])]

def sourceEvidence_functions_writes : List (String × List String) := [("function:calculate", [])]

set_option linter.unusedVariables false

structure Store where

  v0 : Int

  v1 : Int

  v2 : Int

  deriving DecidableEq



inductive Outcome where

  | returned (store : Store) (value : Int)

  | blocked

  | assertionFailure

  deriving DecidableEq

def expression_0 (initial current : Store) (returned : Int) : Int := (current.v0 - current.v2)

def expression_1 (initial current : Store) (returned : Int) : Int := current.v0

def expression_2 (initial current : Store) (returned : Int) : Int := current.v2

def run (initial : Store) : Outcome :=
  let current := initial;
  Outcome.returned current (expression_0 initial current (0 : Int))

def declaredReads (symbol : String) : Bool := ["symbol:calculate.capacity.parameter", "symbol:calculate.threshold.parameter"].contains symbol

example : (["symbol:calculate.capacity.parameter", "symbol:calculate.threshold.parameter"] : List String).all declaredReads = true := by decide

def declaredWrites (symbol : String) : Bool := [].contains symbol

example : ([] : List String).all declaredWrites = true := by decide
end Candidate_1

namespace Candidate_2
def sourceEvidenceOriginalProgramSHA256 : String := "4543587a92da7035744b9c4097b8d22280c0841654fd48df81b2a864535c99a1"

def sourceEvidenceOperationalViewSHA256 : String := "606c876ccf7fdd0ba6c0d37b272b58a5357f46df43b1694fc3b2b87dde4e023f"

def sourceEvidenceSourceSHA256 : String := "e01284d2257aa5afc0781456bd437d9f1417af966b180680e34e8bedff524175"

def sourceEvidenceMetadataJSON : String := "{\"adapter\":\"SourceSoftwareVerificationAdapter@1\",\"assumptions\":[\"The annotation name int denotes exact built-in Python integers; annotations do not enforce runtime types.\",\"The mathematical integer model excludes resource exhaustion and concurrent environment changes.\",\"Native effects and purity retain the source adapter's conservative classification.\"],\"completion_authority\":false,\"effect_summary_assumption\":\"Read/write summaries are derived from the validated expression graph; all other effect flags and the native purity classification are preserved.\",\"effect_summary_audit\":{\"base_program_id\":\"bafkreihf5kxhtkdopq226xtdyphnraefdfp426nue4f2ngus6rm2g3nkne\",\"base_program_sha256\":\"c96906900390f657d29726848b6be59b50fa6d45a6cd31329c7d4e8dcd24b9fb\",\"commands\":[{\"after\":{\"reads\":[\"symbol:calculate.capacity.parameter\",\"symbol:calculate.threshold.parameter\"],\"writes\":[]},\"before\":{\"reads\":[],\"writes\":[]},\"command_id\":\"command:11\",\"retained_effects\":{\"allocates\":[],\"deallocates\":[],\"nondeterministic\":false,\"performs_io\":false,\"raises\":[],\"synchronizes\":false}}],\"functions\":[{\"after\":{\"reads\":[\"symbol:calculate.capacity.parameter\",\"symbol:calculate.threshold.parameter\"],\"writes\":[]},\"before\":{\"reads\":[\"symbol:calculate.capacity.parameter\",\"symbol:calculate.threshold.parameter\"],\"writes\":[]},\"function_id\":\"function:calculate\",\"purity\":\"pure\",\"retained_effects\":{\"allocates\":[],\"deallocates\":[],\"nondeterministic\":false,\"performs_io\":false,\"raises\":[],\"synchronizes\":false}}],\"schema\":\"security-source-program-effect-audit/v1\"},\"effect_summary_contract\":\"closed-command-expression-reads-and-assignment-writes/v1\",\"execution_authority\":false,\"input_type_basis\":\"explicit_int_annotations\",\"language\":\"python\",\"path\":\"source.py\",\"proof_authority\":false,\"security_specification_inferred\":false,\"source_binding_effects_schema\":\"security-source-program-effects-384/v2\",\"source_binding_schema\":\"security-source-program-binding-384/v1\",\"source_semantics_verified\":false,\"source_sha256\":\"e01284d2257aa5afc0781456bd437d9f1417af966b180680e34e8bedff524175\",\"whole_program_semantics_verified\":false}"

def sourceEvidenceSourceReferencesJSON : String := "[{\"container_sha256\":\"\",\"container_uri\":\"\",\"content_cid\":\"\",\"content_sha256\":\"e01284d2257aa5afc0781456bd437d9f1417af966b180680e34e8bedff524175\",\"license_expression\":\"\",\"metadata\":{\"byte_length\":85,\"language\":\"python\",\"path\":\"source.py\"},\"ref_id\":\"source:source.py\",\"review_status\":\"unreviewed\",\"source_id\":\"source.py\",\"source_revision\":\"workspace:local\",\"source_uri\":\"file:///source.py\"}]"

def sourceEvidenceEffectAuditJSON : String := "{\"base_program_id\":\"bafkreihf5kxhtkdopq226xtdyphnraefdfp426nue4f2ngus6rm2g3nkne\",\"base_program_sha256\":\"c96906900390f657d29726848b6be59b50fa6d45a6cd31329c7d4e8dcd24b9fb\",\"commands\":[{\"after\":{\"reads\":[\"symbol:calculate.capacity.parameter\",\"symbol:calculate.threshold.parameter\"],\"writes\":[]},\"before\":{\"reads\":[],\"writes\":[]},\"command_id\":\"command:11\",\"retained_effects\":{\"allocates\":[],\"deallocates\":[],\"nondeterministic\":false,\"performs_io\":false,\"raises\":[],\"synchronizes\":false}}],\"functions\":[{\"after\":{\"reads\":[\"symbol:calculate.capacity.parameter\",\"symbol:calculate.threshold.parameter\"],\"writes\":[]},\"before\":{\"reads\":[\"symbol:calculate.capacity.parameter\",\"symbol:calculate.threshold.parameter\"],\"writes\":[]},\"function_id\":\"function:calculate\",\"purity\":\"pure\",\"retained_effects\":{\"allocates\":[],\"deallocates\":[],\"nondeterministic\":false,\"performs_io\":false,\"raises\":[],\"synchronizes\":false}}],\"schema\":\"security-source-program-effect-audit/v1\"}"

def sourceEvidenceAssumptions : List String := ["The annotation name int denotes exact built-in Python integers; annotations do not enforce runtime types.", "The mathematical integer model excludes resource exhaustion and concurrent environment changes.", "Native effects and purity retain the source adapter's conservative classification.", "Read/write summaries are derived from the validated expression graph; all other effect flags and the native purity classification are preserved."]

def sourceEvidence_proof_authority : Bool := false

def sourceEvidence_execution_authority : Bool := false

def sourceEvidence_completion_authority : Bool := false

def sourceEvidence_source_semantics_verified : Bool := false

def sourceEvidence_whole_program_semantics_verified : Bool := false

def sourceEvidence_security_specification_inferred : Bool := false

def sourceEvidence_commands_reads : List (String × List String) := [("command:11", ["symbol:calculate.capacity.parameter", "symbol:calculate.threshold.parameter"])]

def sourceEvidence_commands_writes : List (String × List String) := [("command:11", [])]

def sourceEvidence_functions_reads : List (String × List String) := [("function:calculate", ["symbol:calculate.capacity.parameter", "symbol:calculate.threshold.parameter"])]

def sourceEvidence_functions_writes : List (String × List String) := [("function:calculate", [])]

set_option linter.unusedVariables false

structure Store where

  v0 : Int

  v1 : Int

  v2 : Int

  deriving DecidableEq



inductive Outcome where

  | returned (store : Store) (value : Int)

  | blocked

  | assertionFailure

  deriving DecidableEq

def expression_0 (initial current : Store) (returned : Int) : Int := (current.v0 * current.v2)

def expression_1 (initial current : Store) (returned : Int) : Int := current.v0

def expression_2 (initial current : Store) (returned : Int) : Int := current.v2

def run (initial : Store) : Outcome :=
  let current := initial;
  Outcome.returned current (expression_0 initial current (0 : Int))

def declaredReads (symbol : String) : Bool := ["symbol:calculate.capacity.parameter", "symbol:calculate.threshold.parameter"].contains symbol

example : (["symbol:calculate.capacity.parameter", "symbol:calculate.threshold.parameter"] : List String).all declaredReads = true := by decide

def declaredWrites (symbol : String) : Bool := [].contains symbol

example : ([] : List String).all declaredWrites = true := by decide
end Candidate_2

end SecuritySourcePrograms
