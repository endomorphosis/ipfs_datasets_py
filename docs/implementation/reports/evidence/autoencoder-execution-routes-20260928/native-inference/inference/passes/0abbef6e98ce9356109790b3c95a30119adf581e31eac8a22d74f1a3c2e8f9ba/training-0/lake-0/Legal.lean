def bound : Nat := 25
def meets (n : Nat) : Bool := decide (bound <= n)
theorem boundary : ((meets 24 = false) /\ (meets 25 = true)) := by
  unfold meets bound
  decide
