def bound : Nat := 26
def meets (n : Nat) : Bool := decide (bound <= n)
theorem boundary : ((meets 25 = false) /\ (meets 26 = true)) := by
  unfold meets bound
  decide
