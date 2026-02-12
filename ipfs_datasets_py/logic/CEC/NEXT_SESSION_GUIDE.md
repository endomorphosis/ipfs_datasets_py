# Next Session Implementation Guide

## Quick Start for Session 2

### 🚀 Critical First Step

**Before any implementation, run:**
```bash
cd /home/runner/work/ipfs_datasets_py/ipfs_datasets_py
git submodule update --init --recursive
```

This initializes the 4 submodules containing source code to port:
- DCEC_Library (parsing source)
- Talos (SPASS source)
- Eng-DCEC (grammar source)
- ShadowProver (Java prover source)

---

## Session 2 Checklist

### Phase 4A.1: Parsing Infrastructure

#### Step 1: Verify Submodules (5 min)
```bash
# Check that these files exist:
ls ipfs_datasets_py/logic/CEC/DCEC_Library/highLevelParsing.py
ls ipfs_datasets_py/logic/CEC/DCEC_Library/cleaning.py
ls ipfs_datasets_py/logic/CEC/DCEC_Library/prototypes.py

# If not found, run: git submodule update --init --recursive
```

#### Step 2: Create dcec_cleaning.py (45 min)
**Location:** `ipfs_datasets_py/logic/native/dcec_cleaning.py`

**Port these functions from DCEC_Library/cleaning.py:**

```python
def strip_whitespace(text: str) -> str:
    """Remove extra whitespace and normalize commas."""
    pass

def strip_comments(text: str) -> str:
    """Remove # comments from text."""
    pass

def consolidate_parens(text: str) -> str:
    """Remove redundant nested parentheses."""
    pass

def check_parens(text: str) -> bool:
    """Validate balanced parentheses."""
    pass

def get_matching_close_paren(text: str, start: int) -> int:
    """Find index of matching close paren."""
    pass

def tuck_functions(text: str) -> str:
    """Transform B(args) to (B args) format."""
    pass
```

**Key Modernizations:**
- Type hints for all parameters and returns
- Comprehensive docstrings
- Modern Python 3 string handling
- Error handling with clear messages

#### Step 3: Test dcec_cleaning.py (30 min)
**Location:** `tests/unit_tests/logic/native/test_dcec_cleaning.py`

**Create tests for:**
- ✅ Whitespace normalization
- ✅ Comment removal (# and mixed with code)
- ✅ Paren consolidation (nested cases)
- ✅ Paren validation (balanced/unbalanced)
- ✅ Matching paren finding
- ✅ Function tucking
- ✅ Edge cases (empty strings, special chars)

**Minimum:** 20 test cases using GIVEN-WHEN-THEN format

#### Step 4: Create dcec_parsing.py (90 min)
**Location:** `ipfs_datasets_py/logic/native/dcec_parsing.py`

**Port from DCEC_Library/highLevelParsing.py:**

```python
from dataclasses import dataclass
from typing import List, Optional, Dict, Any

@dataclass
class ParseToken:
    """Represents a parsed DCEC expression node."""
    value: str
    children: List['ParseToken']
    depth: int = 0
    
    def to_s_expression(self) -> str:
        """Convert to S-expression: (func arg1 arg2)"""
        pass
    
    def to_f_expression(self) -> str:
        """Convert to F-expression: func(arg1, arg2)"""
        pass

def remove_comments(text: str) -> str:
    """Remove semicolon comments."""
    pass

def functorize_symbols(text: str) -> str:
    """Convert operators to function names: ^ → ˆ, * → *, etc."""
    pass

def replace_synonyms(text: str) -> str:
    """Replace synonyms: forall→forAll, Time→Moment, etc."""
    pass

def prefix_logical_functions(text: str) -> str:
    """Convert infix logic to prefix: A and B → (and A B)"""
    pass

def prefix_emdas(text: str) -> str:
    """Convert arithmetic to prefix with PEMDAS."""
    pass

def assign_types(text: str, namespace) -> str:
    """Add inline type annotations."""
    pass

def tokenize(text: str) -> ParseToken:
    """Parse text into token tree."""
    pass
```

#### Step 5: Test dcec_parsing.py (60 min)
**Location:** `tests/unit_tests/logic/native/test_dcec_parsing.py`

**Create tests for:**
- ✅ ParseToken creation and methods
- ✅ Comment removal (semicolons)
- ✅ Symbol functorization
- ✅ Synonym replacement
- ✅ Logical prefix conversion
- ✅ Arithmetic prefix conversion
- ✅ Type assignment
- ✅ Tokenization
- ✅ S/F-expression generation

**Minimum:** 25 test cases

#### Step 6: Integration (30 min)
- Update `ipfs_datasets_py/logic/native/__init__.py`
- Add exports for new functions
- Version bump: 0.2.0 → 0.3.0
- Add usage examples in docstrings
- Test imports work

---

## Expected Deliverables

**Implementation:**
- dcec_cleaning.py (~250 lines)
- dcec_parsing.py (~700 lines)
- **Total:** ~950 lines

**Tests:**
- test_dcec_cleaning.py (~250 lines)
- test_dcec_parsing.py (~350 lines)
- **Total:** ~600 lines

**Grand Total:** ~1,550 lines of code

---

## Validation Checklist

Before committing, verify:

✅ All 45+ tests pass  
✅ No Python 2 syntax remains  
✅ Full type hints on all functions  
✅ Docstrings with examples  
✅ Edge cases handled  
✅ Error messages are clear  
✅ Code follows repository patterns  
✅ Imports work from other modules  

---

## Quick Reference: Porting Strategy

### From Python 2 to Python 3

**Common Changes:**
```python
# Python 2
print "hello"               # ❌
string.find(x) != -1        # ❌
dict.has_key('x')          # ❌
xrange(10)                 # ❌

# Python 3
print("hello")             # ✅
x in string                # ✅
'x' in dict                # ✅
range(10)                  # ✅
```

**Add Type Hints:**
```python
# Before
def func(x, y):
    return x + y

# After
def func(x: int, y: int) -> int:
    """Add two integers."""
    return x + y
```

**Use Dataclasses:**
```python
# Before
class Token:
    def __init__(self, value):
        self.value = value

# After
@dataclass
class Token:
    """Token class."""
    value: str
```

---

## Testing Pattern

Use GIVEN-WHEN-THEN format:

```python
def test_strip_whitespace():
    """Test whitespace normalization."""
    # GIVEN: Text with extra spaces
    text = "hello    world  "
    
    # WHEN: Stripping whitespace
    result = strip_whitespace(text)
    
    # THEN: Should normalize to single spaces
    assert result == "hello world"
```

---

## After Session 2

**Next Session (3) will add:**
- dcec_prototypes.py (port prototypes.py)
- String → Formula integration
- Formula → String integration
- 20+ more tests

**Then Sessions 4-30:**
- Phase 4B: SPASS (80+ rules)
- Phase 4C: Grammar (GF equivalent)
- Phase 4D: ShadowProver (Java port)
- Phase 4E: Polish

---

## Resource Links

**Source Files:**
- `/ipfs_datasets_py/logic/CEC/DCEC_Library/cleaning.py`
- `/ipfs_datasets_py/logic/CEC/DCEC_Library/highLevelParsing.py`
- `/ipfs_datasets_py/logic/CEC/DCEC_Library/prototypes.py`

**Target Location:**
- `/ipfs_datasets_py/logic/native/` (new files go here)

**Test Location:**
- `/tests/unit_tests/logic/native/` (test files go here)

**Documentation:**
- `GAPS_ANALYSIS.md` - What needs porting
- `PHASE4_ROADMAP.md` - Overall plan
- `SESSION_SUMMARY.md` - Session tracking

---

## Time Estimate

**Session 2 Breakdown:**
- Setup & verification: 10 min
- dcec_cleaning.py: 45 min
- test_dcec_cleaning.py: 30 min
- dcec_parsing.py: 90 min
- test_dcec_parsing.py: 60 min
- Integration & testing: 30 min
- Documentation: 15 min

**Total: ~4 hours**

---

## Success Metrics

**After Session 2:**
- ✅ Phase 4A: 33% complete (Part 1 of 3)
- ✅ Overall Phase 4: ~8% complete
- ✅ 45+ new test cases
- ✅ ~1,550 new lines of code
- ✅ Parsing foundation established

**Ready for Session 3:**
- Integrate with Formula objects
- Add prototypes.py functionality
- Complete Phase 4A

---

**Good luck! The foundation is ready, time to code! 🚀**
