def bound : Nat := 24
def meets (n : Nat) : Bool := decide (bound <= n)
theorem boundary : ((meets 23 = false) /\ (meets 24 = true)) := by
  unfold meets bound
  decide
