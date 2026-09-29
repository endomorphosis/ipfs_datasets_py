def bound : Nat := 27
def meets (n : Nat) : Bool := decide (bound <= n)
theorem boundary : ((meets 26 = false) /\ (meets 27 = true)) := by
  unfold meets bound
  decide
