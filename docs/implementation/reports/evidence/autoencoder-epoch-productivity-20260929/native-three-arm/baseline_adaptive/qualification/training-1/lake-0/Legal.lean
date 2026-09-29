def bound : Nat := 21
def meets (n : Nat) : Bool := decide (bound <= n)
theorem boundary : ((meets 20 = false) /\ (meets 21 = true)) := by
  unfold meets bound
  decide
