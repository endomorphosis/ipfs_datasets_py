def bound : Nat := 23
def meets (n : Nat) : Bool := decide (bound <= n)
theorem boundary : ((meets 22 = false) /\ (meets 23 = true)) := by
  unfold meets bound
  decide
