def termKindCode : Nat := 2
def termFingerprint : Nat := 1702048884
def termLocked (k f : Nat) : Bool := decide (k = termKindCode /\ f = termFingerprint)
theorem termDefined : termLocked termKindCode termFingerprint = true := by
  unfold termLocked termKindCode termFingerprint
  decide
def statuteCount : Nat := 2
theorem statuteCountLocked : statuteCount = 2 := by
  unfold statuteCount
  decide
def usedStatute0 : Nat := 1961857050
theorem usedStatuteDefined0 : usedStatute0 = 1961857050 := by
  unfold usedStatute0
  decide
def usedStatute1 : Nat := 721666253
theorem usedStatuteDefined1 : usedStatute1 = 721666253 := by
  unfold usedStatute1
  decide
