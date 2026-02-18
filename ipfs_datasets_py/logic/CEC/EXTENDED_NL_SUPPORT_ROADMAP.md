# Extended Natural Language Support Roadmap

**Version:** 1.0  
**Date:** 2026-02-18  
**Status:** Planning Phase

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [Current Capabilities](#current-capabilities)
3. [Enhancement Goals](#enhancement-goals)
4. [Implementation Plan](#implementation-plan)
5. [Multi-Language Support](#multi-language-support)
6. [Domain-Specific Vocabularies](#domain-specific-vocabularies)
7. [Context-Aware Conversion](#context-aware-conversion)

---

## 📊 Overview

### Objectives

Enhance the natural language to DCEC conversion capabilities with:
1. **Grammar-based parsing** (beyond pattern matching)
2. **Compositional semantics** (proper semantic composition)
3. **Multi-language support** (English, Spanish, French, German)
4. **Domain vocabularies** (legal, medical, technical)
5. **Context-aware conversion** (discourse tracking, pronoun resolution)

### Current State

The native implementation provides **pattern-based NL conversion**:
- 37+ regex patterns for common phrases
- Basic agent/predicate extraction
- Simple linearization (DCEC → English)
- 37 unit tests covering core functionality

### Target State

- **Grammar-based parsing** with compositional semantics
- **4 languages** supported (en, es, fr, de)
- **3 domain vocabularies** (legal, medical, technical)
- **Context tracking** across conversation
- **95%+ accuracy** on benchmark datasets

---

## 🔍 Current Capabilities

### Pattern-Based Conversion

**Location:** `ipfs_datasets_py/logic/CEC/native/nl_converter.py`

**Patterns (37 total):**
```python
OBLIGATION_PATTERNS = [
    r"(?:must|has to|is obligated to|is required to)\s+(.+)",
    r"(?:it is obligatory that|it is mandatory that)\s+(.+)",
    r"(.+)\s+(?:is|are)\s+obligated",
]

BELIEF_PATTERNS = [
    r"(.+)\s+(?:believes?|thinks?)\s+(?:that\s+)?(.+)",
    r"(?:it is believed that|according to)\s+(.+)",
]

PERMISSION_PATTERNS = [
    r"(?:may|is permitted to|is allowed to|can)\s+(.+)",
    r"(?:it is permitted that|it is allowed that)\s+(.+)",
]
```

**Supported Constructs:**
- ✅ Deontic operators (O, P, F)
- ✅ Cognitive operators (B, K, I)
- ✅ Modal operators (□, ◊)
- ✅ Temporal operators (basic)
- ✅ Agent extraction
- ✅ Simple predicate creation

**Limitations:**
- ❌ No compositional semantics
- ❌ Limited to simple sentence structures
- ❌ Cannot handle ambiguity
- ❌ No parse tree generation
- ❌ Single language only (English)
- ❌ No context tracking

### Basic Grammar Support

**Location:** `ipfs_datasets_py/logic/CEC/native/grammar_engine.py`

**Features:**
- Basic parse tree construction
- Grammar rule application
- Simple semantic composition

**Limitations:**
- ❌ Limited grammar coverage
- ❌ No ambiguity resolution
- ❌ No error recovery

---

## 🎯 Enhancement Goals

### Goal 1: Grammar-Based Parsing

**Replace pattern matching with proper grammar:**

```python
# Grammar rules (EBNF-like notation)
sentence := obligation | permission | prohibition | belief | knowledge

obligation := agent "must" action
            | agent "is obligated to" action
            | "it is obligatory that" proposition

permission := agent "may" action
            | agent "is permitted to" action
            | "it is permitted that" proposition

belief := agent "believes" proposition
        | agent "thinks" proposition
        | agent "believes that" proposition
```

**Benefits:**
- Handles complex nested structures
- Generates parse trees
- Supports compositional semantics
- Better error messages

**Implementation:**
- Enhance `grammar_engine.py`
- Expand `dcec_english_grammar.py`
- Add grammar validation
- Support grammar debugging

### Goal 2: Compositional Semantics

**Proper semantic composition:**

```python
# Instead of pattern matching
def convert_obligation_pattern(text: str) -> Formula:
    match = re.match(r"(.+) must (.+)", text)
    return ObligationFormula(...)  # Simple extraction

# Use compositional semantics
def convert_with_semantics(parse_tree: ParseNode) -> Formula:
    # Bottom-up semantic composition
    if parse_tree.rule == "obligation":
        agent_sem = convert_with_semantics(parse_tree.children[0])
        action_sem = convert_with_semantics(parse_tree.children[1])
        return ObligationFormula(action_sem)  # Proper composition
    
    elif parse_tree.rule == "complex_sentence":
        # Handle coordination, subordination, etc.
        left = convert_with_semantics(parse_tree.children[0])
        op = parse_tree.children[1].value  # and, or, implies
        right = convert_with_semantics(parse_tree.children[2])
        return LogicalFormula(op, [left, right])
```

**Benefits:**
- Handles nested structures correctly
- Preserves quantifier scope
- Supports complex operators
- Matches linguistic intuitions

### Goal 3: Ambiguity Resolution

**Handle multiple parse interpretations:**

```python
class AmbiguityResolver:
    def resolve(self, parses: List[ParseTree]) -> ParseTree:
        # Rank parses by:
        # 1. Syntactic preferences
        # 2. Semantic plausibility
        # 3. Context coherence
        # 4. Domain knowledge
        
        scored = [
            (self.score(parse, context), parse)
            for parse in parses
        ]
        
        return max(scored, key=lambda x: x[0])[1]
    
    def score(self, parse: ParseTree, context: Context) -> float:
        score = 0.0
        
        # Syntactic scoring
        score += self.syntactic_score(parse)  # Prefer simpler
        
        # Semantic scoring
        score += self.semantic_score(parse)  # Type-coherent
        
        # Context scoring
        score += self.context_score(parse, context)  # Coherent
        
        return score
```

**Strategies:**
- Prefer simpler structures
- Prefer type-coherent interpretations
- Prefer context-coherent readings
- Use domain knowledge

### Goal 4: Error Recovery

**Handle incomplete/malformed input:**

```python
class RobustParser:
    def parse(self, text: str) -> ParseResult:
        try:
            # Try full parse
            return self.full_parse(text)
        except ParseError as e:
            # Try partial parse with error recovery
            return self.partial_parse(text, e)
    
    def partial_parse(self, text: str, error: ParseError) -> ParseResult:
        # Skip problematic tokens
        # Infer missing constituents
        # Return partial parse with warnings
        pass
```

---

## 📋 Implementation Plan (Phase 5: Weeks 12-16)

### Week 12: Grammar-Based Parsing

**Day 1-2: Grammar Expansion**
- Expand English grammar rules
- Add complex sentence structures
- Support nested operators
- Add grammar validation

**Day 3-4: Parser Enhancement**
- Enhance grammar_engine.py
- Add parse tree generation
- Support ambiguity tracking
- Add error messages

**Day 5: Testing**
- Create 50+ test sentences
- Test all grammar rules
- Validate parse trees
- Test error messages

**Deliverables:**
- Comprehensive English grammar
- Enhanced parser
- 50+ grammar tests

### Week 13: Compositional Semantics

**Day 1-2: Semantic Rules**
- Define semantic composition rules
- Implement bottom-up semantics
- Handle quantifier scoping
- Support nested operators

**Day 3-4: Integration**
- Integrate with parser
- Convert parse trees to formulas
- Validate semantic correctness
- Handle edge cases

**Day 5: Testing**
- Create 40+ semantic tests
- Test complex structures
- Validate correctness
- Compare with patterns

**Deliverables:**
- Compositional semantics
- Parse-to-formula conversion
- 40+ semantic tests

### Week 14: Multi-Language Support

**Day 1: Spanish Grammar**
- Spanish obligation/permission/belief patterns
- Spanish grammar rules
- Agent/action extraction
- 20+ test cases

**Day 2: French Grammar**
- French obligation/permission/belief patterns
- French grammar rules
- Agent/action extraction
- 20+ test cases

**Day 3: German Grammar**
- German obligation/permission/belief patterns
- German grammar rules
- Agent/action extraction
- 20+ test cases

**Day 4: Language Detection**
- Implement language detection
- Auto-select grammar
- Fallback handling
- Cross-language tests

**Day 5: Integration & Testing**
- Integrate all languages
- Multi-language test suite
- Validate accuracy
- Document differences

**Deliverables:**
- 4 language support (en, es, fr, de)
- Language auto-detection
- 60+ multi-language tests

### Week 15: Domain Vocabularies

**Day 1-2: Legal Domain**
- Legal terminology
- Statute/regulation patterns
- Legal operators (rights, duties, liability)
- 25+ legal test cases

**Day 3: Medical Domain**
- Medical terminology
- Patient/provider/treatment patterns
- Medical operators (diagnosis, treatment, contraindication)
- 15+ medical test cases

**Day 4: Technical Domain**
- Technical terminology
- System/component/function patterns
- Technical operators (requires, provides, depends)
- 15+ technical test cases

**Day 5: Domain Selection**
- Implement domain detection
- Domain-specific parsing
- Vocabulary augmentation
- Domain tests

**Deliverables:**
- 3 domain vocabularies
- Domain auto-detection
- 55+ domain tests

### Week 16: Context-Aware Conversion

**Day 1-2: Context Tracking**
- Discourse representation
- Entity tracking
- Reference resolution
- Conversation state

**Day 3: Pronoun Resolution**
- Implement coreference resolution
- Pronoun → entity mapping
- Gender/number agreement
- 20+ resolution tests

**Day 4: Dialogue Understanding**
- Multi-turn conversation
- Context accumulation
- Clarification questions
- Dialogue tests

**Day 5: Integration & Polish**
- Integrate all components
- End-to-end testing
- Documentation
- Performance validation

**Deliverables:**
- Context-aware conversion
- Pronoun resolution
- Dialogue support
- 30+ context tests

---

## 🌐 Multi-Language Support

### Spanish Support

**Obligation Patterns:**
```python
SPANISH_OBLIGATION_PATTERNS = [
    r"(?:debe|tiene que|está obligado a)\s+(.+)",
    r"es obligatorio que\s+(.+)",
    r"es necesario que\s+(.+)",
]
```

**Example Sentences:**
- "El agente debe actuar" → O(act(agent))
- "Es obligatorio que el agente cumpla" → O(comply(agent))
- "El agente tiene que realizar la acción" → O(performAction(agent))

**Grammar Rules:**
```
sentence := obligation | permission | belief

obligation := subject "debe" verb_phrase
            | "es obligatorio que" clause

subject := article noun
         | article adjective noun
         | proper_noun
```

### French Support

**Obligation Patterns:**
```python
FRENCH_OBLIGATION_PATTERNS = [
    r"(?:doit|est obligé de)\s+(.+)",
    r"il est obligatoire (?:que|de)\s+(.+)",
    r"il faut que\s+(.+)",
]
```

**Example Sentences:**
- "L'agent doit agir" → O(act(agent))
- "Il est obligatoire que l'agent agisse" → O(act(agent))
- "L'agent est obligé d'agir" → O(act(agent))

### German Support

**Obligation Patterns:**
```python
GERMAN_OBLIGATION_PATTERNS = [
    r"(?:muss|ist verpflichtet)\s+(.+)",
    r"es ist (?:obligatorisch|erforderlich),? dass\s+(.+)",
]
```

**Example Sentences:**
- "Der Agent muss handeln" → O(act(agent))
- "Es ist obligatorisch, dass der Agent handelt" → O(act(agent))
- "Der Agent ist verpflichtet zu handeln" → O(act(agent))

### Language Detection

```python
from langdetect import detect

class MultilingualConverter:
    def __init__(self):
        self.converters = {
            'en': EnglishConverter(),
            'es': SpanishConverter(),
            'fr': FrenchConverter(),
            'de': GermanConverter(),
        }
    
    def convert(self, text: str, language: str = None) -> Formula:
        if language is None:
            language = detect(text)
        
        converter = self.converters.get(language)
        if converter is None:
            raise ValueError(f"Unsupported language: {language}")
        
        return converter.convert(text)
```

---

## 📚 Domain-Specific Vocabularies

### Legal Domain

**Terminology:**
- **Obligation:** must, shall, required to, obligated to
- **Permission:** may, allowed to, permitted to
- **Prohibition:** must not, shall not, forbidden to
- **Right:** has the right to, entitled to
- **Duty:** has the duty to, responsible for
- **Liability:** liable for, accountable for

**Example Patterns:**
```python
LEGAL_OBLIGATION_PATTERNS = [
    r"(\w+)\s+shall\s+(.+)",  # Formal legal
    r"(\w+)\s+is required to\s+(.+)",
    r"it is the duty of\s+(\w+)\s+to\s+(.+)",
]

LEGAL_PROHIBITION_PATTERNS = [
    r"(\w+)\s+shall not\s+(.+)",
    r"(\w+)\s+is prohibited from\s+(.+)",
    r"it is unlawful for\s+(\w+)\s+to\s+(.+)",
]
```

**Example Sentences:**
- "The party shall comply with all regulations" → O(comply(party, regulations))
- "The contractor is prohibited from disclosing" → F(disclose(contractor))
- "The licensee has the right to use the software" → P(use(licensee, software))

### Medical Domain

**Terminology:**
- **Diagnosis:** diagnosed with, suffering from, has condition
- **Treatment:** prescribed, administered, given, should receive
- **Contraindication:** contraindicated, should not receive, avoid
- **Side effect:** may cause, can result in, associated with

**Example Patterns:**
```python
MEDICAL_DIAGNOSIS_PATTERNS = [
    r"(?:patient|individual)\s+(?:is\s+)?diagnosed with\s+(.+)",
    r"(?:patient|individual)\s+(?:has|suffers from)\s+(.+)",
]

MEDICAL_TREATMENT_PATTERNS = [
    r"(?:patient|individual)\s+should\s+(?:receive|take)\s+(.+)",
    r"prescribed\s+(.+)\s+for\s+(\w+)",
]
```

**Example Sentences:**
- "Patient is diagnosed with hypertension" → Diagnosis(patient, hypertension)
- "Patient should receive aspirin" → Treatment(patient, aspirin)
- "Aspirin is contraindicated for patients with bleeding disorders" → Contraindication(aspirin, bleeding_disorder)

### Technical Domain

**Terminology:**
- **Requires:** requires, needs, depends on
- **Provides:** provides, supplies, offers
- **Configuration:** configured with, set to, uses
- **Compatibility:** compatible with, works with, supports

**Example Patterns:**
```python
TECHNICAL_DEPENDENCY_PATTERNS = [
    r"(\w+)\s+requires\s+(.+)",
    r"(\w+)\s+depends on\s+(.+)",
]

TECHNICAL_PROVISION_PATTERNS = [
    r"(\w+)\s+provides\s+(.+)",
    r"(\w+)\s+supplies\s+(.+)",
]
```

**Example Sentences:**
- "The module requires Python 3.12" → Requires(module, python_3_12)
- "The API provides RESTful endpoints" → Provides(api, rest_endpoints)
- "The system is compatible with Linux" → Compatible(system, linux)

---

## 🧠 Context-Aware Conversion

### Discourse Representation

**Track entities and propositions:**

```python
class DiscourseContext:
    def __init__(self):
        self.entities: Dict[str, Entity] = {}
        self.propositions: List[Formula] = []
        self.focus_stack: List[Entity] = []
    
    def add_entity(self, name: str, entity_type: str):
        entity = Entity(name, entity_type)
        self.entities[name] = entity
        self.focus_stack.append(entity)
    
    def add_proposition(self, formula: Formula):
        self.propositions.append(formula)
    
    def resolve_reference(self, reference: str) -> Optional[Entity]:
        # Try exact match
        if reference in self.entities:
            return self.entities[reference]
        
        # Try pronoun resolution
        if reference in ('he', 'she', 'it', 'they'):
            return self.resolve_pronoun(reference)
        
        return None
```

### Pronoun Resolution

**Resolve pronouns to entities:**

```python
class PronounResolver:
    def resolve(self, pronoun: str, context: DiscourseContext) -> Optional[Entity]:
        # Simple recency-based resolution
        for entity in reversed(context.focus_stack):
            if self.matches_gender_number(pronoun, entity):
                return entity
        return None
    
    def matches_gender_number(self, pronoun: str, entity: Entity) -> bool:
        pronoun_features = {
            'he': {'gender': 'male', 'number': 'singular'},
            'she': {'gender': 'female', 'number': 'singular'},
            'it': {'gender': 'neuter', 'number': 'singular'},
            'they': {'number': 'plural'},
        }
        
        features = pronoun_features.get(pronoun, {})
        
        if 'gender' in features and entity.gender != features['gender']:
            return False
        if 'number' in features and entity.number != features['number']:
            return False
        
        return True
```

**Example:**
```python
converter = ContextAwareConverter()

# First sentence
result1 = converter.convert("The agent must act")
# Creates entity: agent
# Produces: O(act(agent))

# Second sentence (pronoun reference)
result2 = converter.convert("He believes it is necessary")
# Resolves: He → agent
# Produces: B(agent, necessary)

# Third sentence
result3 = converter.convert("Therefore, the agent will act")
# Maintains reference: agent
# Produces: act(agent)
```

### Dialogue Understanding

**Multi-turn conversation:**

```python
class DialogueManager:
    def __init__(self):
        self.context = DiscourseContext()
        self.history: List[Tuple[str, Formula]] = []
    
    def process_utterance(self, utterance: str) -> Formula:
        # Parse with context
        formula = self.parse_with_context(utterance, self.context)
        
        # Update context
        self.context.add_proposition(formula)
        self.history.append((utterance, formula))
        
        # Extract new entities
        entities = self.extract_entities(formula)
        for entity in entities:
            self.context.add_entity(entity.name, entity.type)
        
        return formula
    
    def clarify(self, question: str) -> str:
        # Handle clarification questions
        pass
```

---

## 📊 Success Metrics

### Accuracy Targets

| Metric | Current | Target |
|--------|---------|--------|
| Simple sentences | 90% | 95% |
| Complex sentences | 60% | 90% |
| Multi-language | N/A | 85% |
| Domain-specific | N/A | 90% |
| With context | N/A | 85% |

### Benchmark Datasets

1. **DCEC-English-100** - 100 hand-crafted English sentences
2. **DCEC-Multi-50** - 50 sentences × 4 languages = 200 total
3. **DCEC-Legal-50** - 50 legal domain sentences
4. **DCEC-Medical-30** - 30 medical domain sentences
5. **DCEC-Dialogue-20** - 20 multi-turn dialogues

---

## 📝 Conclusion

This extended NL support roadmap provides a comprehensive plan to enhance natural language capabilities from **pattern-matching** to **grammar-based parsing with compositional semantics**, supporting:

1. ✅ **4 languages** (English, Spanish, French, German)
2. ✅ **3 domains** (Legal, Medical, Technical)
3. ✅ **Context-aware** conversion with pronoun resolution
4. ✅ **95%+ accuracy** on benchmark datasets
5. ✅ **Robust parsing** with error recovery

**Implementation Timeline:** 5 weeks (Weeks 12-16 of overall plan)

---

**Document Version:** 1.0  
**Last Updated:** 2026-02-18  
**Status:** Ready for Implementation  
**Implementation:** Phase 5 (Weeks 12-16)
