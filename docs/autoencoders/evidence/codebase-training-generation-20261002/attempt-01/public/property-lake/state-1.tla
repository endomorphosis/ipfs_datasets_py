---- MODULE BoundedNativeState ----
EXTENDS Integers, Sequences

MaxSteps == 1
v0Domain == (-1)..1
v1Domain == (-1)..1
v2Domain == BOOLEAN
v3Domain == BOOLEAN
VARIABLES v0, v1, v2, v3, step, actionLabel
vars == <<v0, v1, v2, v3, step, actionLabel>>
SourceVariableAliases == <<<<"state:input:0", "v0">>, <<"input_0", "v0">>, <<"state:input:1", "v1">>, <<"input_1", "v1">>, <<"state:result", "v2">>, <<"result", "v2">>, <<"state:returned", "v3">>, <<"returned", "v3">>>>
ActionIntentOrigins == <<>>
ActionEventOrigins == <<>>
SyntheticActionOrigins == <<>>
RuntimeEventOccurrencesAttested == FALSE
TypeOK == v0 \in v0Domain /\ v1 \in v1Domain /\ v2 \in v2Domain /\ v3 \in v3Domain /\ step \in 0..MaxSteps /\ actionLabel \in {"initial", "stutter", "source:return:000", "source:return:001", "source:return:002", "source:return:003", "source:return:004", "source:return:005", "source:return:006", "source:return:007", "source:return:008"}
Pred0 == v0 = (-1) /\ v1 = (-1) /\ v2 = FALSE /\ v3 = FALSE
Pred1 == v0 = (-1) /\ v1 = 0 /\ v2 = FALSE /\ v3 = FALSE
Pred2 == v0 = (-1) /\ v1 = 1 /\ v2 = FALSE /\ v3 = FALSE
Pred3 == v0 = 0 /\ v1 = (-1) /\ v2 = FALSE /\ v3 = FALSE
Pred4 == v0 = 0 /\ v1 = 0 /\ v2 = FALSE /\ v3 = FALSE
Pred5 == v0 = 0 /\ v1 = 1 /\ v2 = FALSE /\ v3 = FALSE
Pred6 == v0 = 1 /\ v1 = (-1) /\ v2 = FALSE /\ v3 = FALSE
Pred7 == v0 = 1 /\ v1 = 0 /\ v2 = FALSE /\ v3 = FALSE
Pred8 == v0 = 1 /\ v1 = 1 /\ v2 = FALSE /\ v3 = FALSE
Pred9 == v2 = FALSE /\ v3 = FALSE
Pred10 == v0' = (-1) /\ v1' = (-1) /\ v2' = FALSE /\ v3' = TRUE
Pred11 == v0' = (-1) /\ v1' = 0 /\ v2' = TRUE /\ v3' = TRUE
Pred12 == v0' = (-1) /\ v1' = 1 /\ v2' = TRUE /\ v3' = TRUE
Pred13 == v0' = 0 /\ v1' = (-1) /\ v2' = FALSE /\ v3' = TRUE
Pred14 == v0' = 0 /\ v1' = 0 /\ v2' = FALSE /\ v3' = TRUE
Pred15 == v0' = 0 /\ v1' = 1 /\ v2' = TRUE /\ v3' = TRUE
Pred16 == v0' = 1 /\ v1' = (-1) /\ v2' = FALSE /\ v3' = TRUE
Pred17 == v0' = 1 /\ v1' = 0 /\ v2' = FALSE /\ v3' = TRUE
Pred18 == v0' = 1 /\ v1' = 1 /\ v2' = FALSE /\ v3' = TRUE
Init == TypeOK /\ step = 0 /\ actionLabel = "initial" /\ Pred9
Action0 == Pred0 /\ Pred10 /\ actionLabel' = "source:return:000" /\ v0' = v0 /\ v1' = v1
Action1 == Pred1 /\ Pred11 /\ actionLabel' = "source:return:001" /\ v0' = v0 /\ v1' = v1
Action2 == Pred2 /\ Pred12 /\ actionLabel' = "source:return:002" /\ v0' = v0 /\ v1' = v1
Action3 == Pred3 /\ Pred13 /\ actionLabel' = "source:return:003" /\ v0' = v0 /\ v1' = v1
Action4 == Pred4 /\ Pred14 /\ actionLabel' = "source:return:004" /\ v0' = v0 /\ v1' = v1
Action5 == Pred5 /\ Pred15 /\ actionLabel' = "source:return:005" /\ v0' = v0 /\ v1' = v1
Action6 == Pred6 /\ Pred16 /\ actionLabel' = "source:return:006" /\ v0' = v0 /\ v1' = v1
Action7 == Pred7 /\ Pred17 /\ actionLabel' = "source:return:007" /\ v0' = v0 /\ v1' = v1
Action8 == Pred8 /\ Pred18 /\ actionLabel' = "source:return:008" /\ v0' = v0 /\ v1' = v1
Next == TypeOK /\ TypeOK' /\ step < MaxSteps /\ step' = step + 1 /\ (Action0 \/ Action1 \/ Action2 \/ Action3 \/ Action4 \/ Action5 \/ Action6 \/ Action7 \/ Action8)
Spec == Init /\ [][Next]_vars
Safety == TypeOK
====
