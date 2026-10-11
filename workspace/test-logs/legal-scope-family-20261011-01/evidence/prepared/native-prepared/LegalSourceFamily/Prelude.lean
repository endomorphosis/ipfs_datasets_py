namespace LegalSourceFamily
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

end LegalSourceFamily
