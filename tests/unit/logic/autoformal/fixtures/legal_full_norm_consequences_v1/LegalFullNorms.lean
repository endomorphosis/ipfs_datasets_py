namespace LegalFullNorms
set_option autoImplicit false
structure Interpretation (Entity Agent : Type) where
  agent : String → Agent
  cognitive : String → Agent → (Nat → Prop) → Nat → Prop
  constant : String → Entity
  function : String → List Entity → Entity
  atom : String → List Entity → Nat → Prop
  modal : String → List Entity → Option String → (Nat → Prop) → Nat → Prop
  frame : Entity → String → Entity → Prop
  frameScalar : Entity → String → Entity
  member : Entity → Entity → Prop
  subclass : Entity → Entity → Prop

def nextTime (p : Nat → Prop) (t : Nat) : Prop := p (t + 1)
def alwaysTime (p : Nat → Prop) (t : Nat) : Prop := ∀ u, t ≤ u → p u
def eventuallyTime (p : Nat → Prop) (t : Nat) : Prop := ∃ u, t ≤ u ∧ p u
def untilTime (p q : Nat → Prop) (t : Nat) : Prop :=
  ∃ u, t ≤ u ∧ q u ∧ ∀ v, t ≤ v → v < u → p v
def sinceTime (p q : Nat → Prop) (t : Nat) : Prop :=
  ∃ u, u ≤ t ∧ q u ∧ ∀ v, u < v → v ≤ t → p v
def weakUntilTime (p q : Nat → Prop) (t : Nat) : Prop := untilTime p q t ∨ alwaysTime p t
def releaseTime (p q : Nat → Prop) (t : Nat) : Prop := ¬ untilTime (fun u => ¬ p u) (fun u => ¬ q u) t

namespace CandidateA
def formula_0 {Entity Agent : Type} (i : Interpretation Entity Agent) : Nat → Prop := (fun t => ∀ v0 : Entity, (fun t => ∀ v1 : Entity, (fun t => ∀ v2 : Entity, (fun t => ((i.modal "deontic:P" [] none (fun t => ((fun t => i.atom "Assign" [v0, v1] t) t) ∨ ((fun t => i.atom "Transfer" [v0, v1] t) t))) t) → ((fun t => i.atom "Approve" [v2, v0] t) t)) t) t) t)
def permittedActionsAt {Entity Agent : Type} (i : Interpretation Entity Agent) (r d : Entity) : Nat → Prop := (i.modal "deontic:P" [] none (fun t => ((fun t => i.atom "Assign" [r, d] t) t) ∨ ((fun t => i.atom "Transfer" [r, d] t) t)))
def approvalAt {Entity Agent : Type} (i : Interpretation Entity Agent) (s r : Entity) : Nat → Prop := (fun t => i.atom "Approve" [s, r] t)
theorem norm_instance {Entity Agent : Type} (i : Interpretation Entity Agent) (t : Nat) (r d s : Entity)
    (hNorm : formula_0 i t) : permittedActionsAt i r d t → approvalAt i s r t := by
  exact hNorm r d s
#print axioms norm_instance
theorem approval_from_permission {Entity Agent : Type} (i : Interpretation Entity Agent) (t : Nat) (r d s : Entity)
    (hNorm : formula_0 i t) (hPermit : permittedActionsAt i r d t) : approvalAt i s r t := by
  exact hNorm r d s hPermit
#print axioms approval_from_permission
end CandidateA
namespace CandidateB
def formula_0 {Entity Agent : Type} (i : Interpretation Entity Agent) : Nat → Prop := (fun t => ∀ v0 : Entity, (fun t => ∀ v1 : Entity, (fun t => ∀ v2 : Entity, (i.modal "deontic:P" [] none (fun t => ((fun t => ((fun t => i.atom "Assign" [v0, v1] t) t) ∨ ((fun t => i.atom "Transfer" [v0, v1] t) t)) t) → ((fun t => i.atom "Approve" [v2, v0] t) t))) t) t) t)
def permittedImplicationAt {Entity Agent : Type} (i : Interpretation Entity Agent) (r d s : Entity) : Nat → Prop := (i.modal "deontic:P" [] none (fun t => ((fun t => ((fun t => i.atom "Assign" [r, d] t) t) ∨ ((fun t => i.atom "Transfer" [r, d] t) t)) t) → ((fun t => i.atom "Approve" [s, r] t) t)))
theorem modal_instance {Entity Agent : Type} (i : Interpretation Entity Agent) (t : Nat) (r d s : Entity)
    (hNorm : formula_0 i t) : permittedImplicationAt i r d s t := by
  exact hNorm r d s
#print axioms modal_instance
end CandidateB
end LegalFullNorms
