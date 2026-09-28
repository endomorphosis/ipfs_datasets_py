def bound : Nat := 30
def meets (n : Nat) : Bool := decide (bound <= n)
theorem boundary : ((meets 29 = false) /\ (meets 30 = true)) := by
  unfold meets bound
  decide
