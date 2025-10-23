
; Deontic logic axioms
(declare-sort Agent 0)
(declare-sort Proposition 0)

; Deontic operators
(declare-fun Obligatory (Agent Proposition) Bool)
(declare-fun Permitted (Agent Proposition) Bool)
(declare-fun Forbidden (Agent Proposition) Bool)

; Consistency axioms
(assert (forall ((a Agent) (p Proposition)) 
    (not (and (Obligatory a p) (Forbidden a p)))))
(assert (forall ((a Agent) (p Proposition))
    (=> (Obligatory a p) (Permitted a p))))

; Formula to prove/check
(obligatory board_of_directors exercise_oversight_of_the_corporations_operations)

; Check satisfiability
(check-sat)
(get-model)
