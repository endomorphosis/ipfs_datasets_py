def bound : Nat := 20
def meets (n : Nat) : Bool := decide (bound <= n)
theorem boundary : ((meets 19 = false) /\ (meets 20 = true)) := by
  unfold meets bound
  decide
