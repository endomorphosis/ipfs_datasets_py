"""
LLM Prompts for TDFOL Natural Language Conversion.

This module provides prompt templates and few-shot examples for converting
natural language to TDFOL (Temporal Deontic First-Order Logic) using LLMs.
"""

from typing import Dict, List, Optional


# Base system prompt for TDFOL conversion
SYSTEM_PROMPT = """You are an expert in converting natural language to TDFOL (Temporal Deontic First-Order Logic).

TDFOL Syntax:
- Universal quantifier: ∀x.P(x) or forall(x, P(x))
- Existential quantifier: ∃x.P(x) or exists(x, P(x))
- Logical operators: → (implies), ∧ (and), ∨ (or), ¬ (not)
- Temporal operators: G (always/globally), F (eventually/finally), X (next), U (until)
- Deontic operators: O (obligation), P (permission), F (forbidden)
- Modal operators: K (knowledge), B (belief)

Convert natural language to valid TDFOL formulas. Be precise and maintain logical structure."""


# Operator-specific prompts
OPERATOR_PROMPTS = {
    "universal": """Universal quantification (∀):
Examples:
- "All X are Y" → ∀x.(X(x) → Y(x))
- "Every person must..." → ∀x.(Person(x) → ...)
- "Each contractor..." → ∀x.(Contractor(x) → ...)""",
    
    "existential": """Existential quantification (∃):
Examples:
- "Some X are Y" → ∃x.(X(x) ∧ Y(x))
- "There exists a person who..." → ∃x.(Person(x) ∧ ...)
- "At least one contractor..." → ∃x.(Contractor(x) ∧ ...)""",
    
    "obligation": """Deontic Obligation (O):
Examples:
- "X must Y" → O(Y(x))
- "X is required to Y" → O(Y(x))
- "X shall Y" → O(Y(x))
- "X is obligated to Y" → O(Y(x))""",
    
    "permission": """Deontic Permission (P):
Examples:
- "X may Y" → P(Y(x))
- "X is allowed to Y" → P(Y(x))
- "X can Y" → P(Y(x))
- "X is permitted to Y" → P(Y(x))""",
    
    "forbidden": """Deontic Forbidden (F):
Examples:
- "X must not Y" → F(Y(x))
- "X is prohibited from Y" → F(Y(x))
- "X shall not Y" → F(Y(x))
- "X is forbidden to Y" → F(Y(x))""",
    
    "temporal_always": """Temporal Always (G):
Examples:
- "X always Y" → G(Y(x))
- "X will always Y" → G(Y(x))
- "X perpetually Y" → G(Y(x))""",
    
    "temporal_eventually": """Temporal Eventually (F):
Examples:
- "X will eventually Y" → F(Y(x))
- "X will Y at some point" → F(Y(x))
- "X will someday Y" → F(Y(x))""",
}


# Few-shot examples organized by complexity
FEW_SHOT_EXAMPLES = {
    "basic": [
        {
            "input": "All contractors must pay taxes.",
            "output": "∀x.(Contractor(x) → O(PayTaxes(x)))",
            "explanation": "Universal quantification over contractors with obligation"
        },
        {
            "input": "Every employee can access the system.",
            "output": "∀x.(Employee(x) → P(Access(x, system)))",
            "explanation": "Universal quantification with permission"
        },
        {
            "input": "No one may enter without authorization.",
            "output": "∀x.(¬Authorized(x) → F(Enter(x)))",
            "explanation": "Universal quantification with forbidden action"
        },
    ],
    
    "intermediate": [
        {
            "input": "All managers must review reports weekly.",
            "output": "∀x.(Manager(x) → G(O(Review(x, reports) ∧ Weekly())))",
            "explanation": "Universal with temporal always and obligation"
        },
        {
            "input": "Contractors shall submit invoices within 30 days.",
            "output": "∀x.(Contractor(x) → O(F(Submit(x, invoice) ∧ Within(30, days))))",
            "explanation": "Universal with obligation and temporal eventually"
        },
        {
            "input": "Users who are admins can modify settings.",
            "output": "∀x.((User(x) ∧ Admin(x)) → P(Modify(x, settings)))",
            "explanation": "Universal with compound condition and permission"
        },
    ],
    
    "advanced": [
        {
            "input": "All contractors must pay taxes unless they are exempt.",
            "output": "∀x.(Contractor(x) → (¬Exempt(x) → O(PayTaxes(x))))",
            "explanation": "Universal with conditional obligation"
        },
        {
            "input": "Every manager knows that employees must complete training.",
            "output": "∀x.(Manager(x) → K(∀y.(Employee(y) → O(Complete(y, training)))))",
            "explanation": "Universal with modal knowledge and nested obligation"
        },
        {
            "input": "If a contractor submits late, they must pay a penalty and always submit on time in the future.",
            "output": "∀x.(Contractor(x) → (SubmitLate(x) → (O(PayPenalty(x)) ∧ G(O(SubmitOnTime(x))))))",
            "explanation": "Universal with conditional obligations and temporal operator"
        },
    ],
}


# Validation and error correction prompts
VALIDATION_PROMPT = """Validate the TDFOL formula:
1. Check syntax correctness
2. Verify all quantifiers are properly bound
3. Ensure logical operators are used correctly
4. Confirm temporal/deontic operators are appropriate

If errors found, provide corrected formula."""


ERROR_CORRECTION_PROMPT = """The following TDFOL formula has errors:
{formula}

Errors detected:
{errors}

Please provide a corrected version that:
1. Fixes all syntax errors
2. Maintains the original semantic meaning
3. Uses proper TDFOL operators"""


def build_conversion_prompt(
    text: str,
    include_examples: bool = True,
    complexity: str = "basic",
    operator_hints: Optional[List[str]] = None
) -> str:
    """
    Build a complete prompt for NL to TDFOL conversion.
    
    Args:
        text: Natural language text to convert
        include_examples: Whether to include few-shot examples
        complexity: Example complexity level ("basic", "intermediate", "advanced")
        operator_hints: List of operator types to include hints for
    
    Returns:
        Complete prompt string
    """
    prompt_parts = [SYSTEM_PROMPT, ""]
    
    # Add operator-specific hints if requested
    if operator_hints:
        prompt_parts.append("Relevant operators:")
        for hint in operator_hints:
            if hint in OPERATOR_PROMPTS:
                prompt_parts.append(OPERATOR_PROMPTS[hint])
        prompt_parts.append("")
    
    # Add few-shot examples if requested
    if include_examples:
        examples = FEW_SHOT_EXAMPLES.get(complexity, FEW_SHOT_EXAMPLES["basic"])
        prompt_parts.append("Examples:")
        for ex in examples:
            prompt_parts.append(f"Input: {ex['input']}")
            prompt_parts.append(f"Output: {ex['output']}")
            prompt_parts.append("")
    
    # Add the actual conversion request
    prompt_parts.append(f"Now convert this text to TDFOL:")
    prompt_parts.append(f"Input: {text}")
    prompt_parts.append(f"Output:")
    
    return "\n".join(prompt_parts)


def build_validation_prompt(formula: str) -> str:
    """Build a prompt for formula validation."""
    return f"{VALIDATION_PROMPT}\n\nFormula: {formula}"


def build_error_correction_prompt(formula: str, errors: List[str]) -> str:
    """Build a prompt for error correction."""
    error_list = "\n".join(f"- {err}" for err in errors)
    return ERROR_CORRECTION_PROMPT.format(formula=formula, errors=error_list)


def get_operator_hints_for_text(text: str) -> List[str]:
    """
    Analyze text and suggest relevant operator hints.
    
    Args:
        text: Natural language text
    
    Returns:
        List of operator hint keys
    """
    text_lower = text.lower()
    hints = []
    
    # Check for quantifiers
    if any(word in text_lower for word in ["all", "every", "each"]):
        hints.append("universal")
    if any(word in text_lower for word in ["some", "exists", "there is"]):
        hints.append("existential")
    
    # Check for deontic operators
    if any(word in text_lower for word in ["must", "required", "shall", "obligated"]):
        hints.append("obligation")
    if any(word in text_lower for word in ["may", "allowed", "can", "permitted"]):
        hints.append("permission")
    if any(word in text_lower for word in ["must not", "prohibited", "forbidden", "shall not"]):
        hints.append("forbidden")
    
    # Check for temporal operators
    if any(word in text_lower for word in ["always", "perpetually", "forever"]):
        hints.append("temporal_always")
    if any(word in text_lower for word in ["eventually", "someday", "will"]):
        hints.append("temporal_eventually")
    
    return hints
