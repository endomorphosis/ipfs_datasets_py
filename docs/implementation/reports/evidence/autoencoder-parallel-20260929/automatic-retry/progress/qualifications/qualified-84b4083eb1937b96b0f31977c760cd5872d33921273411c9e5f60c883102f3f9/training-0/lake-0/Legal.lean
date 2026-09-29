def bound : Nat := 22
def meets (n : Nat) : Bool := decide (bound <= n)
theorem boundary : ((meets 21 = false) /\ (meets 22 = true)) := by
  unfold meets bound
  decide
