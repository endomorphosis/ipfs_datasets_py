# CEC Quick Start Guide

**Get started with CEC (Cognitive Event Calculus) in 5 minutes!**

---

## 📋 Table of Contents

1. [Prerequisites](#prerequisites)
2. [Installation](#installation)
3. [5-Minute Tutorial](#5-minute-tutorial)
4. [Common Use Cases](#common-use-cases)
5. [Troubleshooting](#troubleshooting)
6. [Next Steps](#next-steps)

---

## ✅ Prerequisites

- **Python 3.12+** (required)
- **pip** (package manager)
- **Basic Python knowledge**
- **5 minutes of your time!**

That's it! No external dependencies required.

---

## 📦 Installation

### Option 1: Install from Repository (Recommended)

```bash
# Clone repository
git clone https://github.com/endomorphosis/ipfs_datasets_py.git
cd ipfs_datasets_py

# Install in development mode
pip install -e .

# Verify installation
python -c "from ipfs_datasets_py.logic.CEC.native import DCECContainer; print('✅ CEC installed successfully!')"
```

### Option 2: Install with Test Dependencies

```bash
# Install with testing tools
pip install -e ".[test]"

# Run tests to verify
pytest tests/unit_tests/logic/CEC/
```

---

## ⚡ 5-Minute Tutorial

### Step 1: Create Your First DCEC Container (30 seconds)

```python
from ipfs_datasets_py.logic.CEC.native import DCECContainer

# Create a container to hold logical statements
container = DCECContainer()

# Add an obligation
obligation = container.create_obligation("robot", "cleanRoom")
print(f"Created: {obligation}")
# Output: O(cleanRoom(robot))

# Add a belief
belief = container.create_belief("robot", "roomIsDirty")
print(f"Created: {belief}")
# Output: B(robot, roomIsDirty)

print(f"✅ Container has {len(container.statements)} statements")
```

**What just happened?**
- Created a logical container
- Added an obligation (robot MUST clean room)
- Added a belief (robot BELIEVES room is dirty)

---

### Step 2: Convert Natural Language (1 minute)

```python
from ipfs_datasets_py.logic.CEC.native.nl_converter import NaturalLanguageConverter

# Create converter
converter = NaturalLanguageConverter()

# Convert English to formal logic
sentences = [
    "The robot must perform the task",
    "The robot believes the task is complete",
    "It is permitted to open the door",
    "The robot knows the password"
]

for sentence in sentences:
    dcec = converter.english_to_dcec(sentence)
    print(f"'{sentence}' → {dcec}")

# Output:
# 'The robot must perform the task' → O(performTask(robot))
# 'The robot believes the task is complete' → B(robot, taskIsComplete)
# 'It is permitted to open the door' → P(openDoor)
# 'The robot knows the password' → K(robot, password)
```

**What just happened?**
- Converted natural language to formal DCEC logic
- Used pattern-based recognition
- Got machine-readable formulas

---

### Step 3: Prove Theorems (2 minutes)

```python
from ipfs_datasets_py.logic.CEC.native.prover_core import TheoremProver

# Create theorem prover
prover = TheoremProver()

# Example 1: Simple modus ponens
print("\n=== Example 1: Modus Ponens ===")
prover.clear()
prover.add_axiom("A → B")
prover.add_axiom("A")
result = prover.prove("B")
print(f"Can we prove B? {result.is_proven}")
print(f"Proof steps: {len(result.proof_steps)}")

# Example 2: Chain of reasoning
print("\n=== Example 2: Chain Reasoning ===")
prover.clear()
prover.add_axiom("A → B")
prover.add_axiom("B → C")
prover.add_axiom("A")
result = prover.prove("C")
print(f"Can we prove C? {result.is_proven}")
print(f"Proof steps: {len(result.proof_steps)}")

# Example 3: Deontic reasoning
print("\n=== Example 3: Deontic Logic ===")
prover.clear()
prover.add_axiom("O(performTask(robot))")  # Obligation
prover.add_axiom("O(φ) → P(φ)")            # Obligation implies permission
result = prover.prove("P(performTask(robot))")
print(f"Can we prove permission? {result.is_proven}")
```

**What just happened?**
- Created automated theorem prover
- Proved theorems using logical inference
- Used deontic logic rules (obligations → permissions)

---

### Step 4: Build a Knowledge Base (1.5 minutes)

```python
from ipfs_datasets_py.logic.CEC.native.dcec_knowledge_base import DCECKnowledgeBase

# Create knowledge base
kb = DCECKnowledgeBase()

# Add rules about robot behavior
kb.add_rule("O(performTask(robot)) → B(robot, mustWork)")
kb.add_rule("B(robot, mustWork) → I(robot, startTask)")
kb.add_rule("I(robot, startTask) → Happens(taskStart, t)")

# Add facts
kb.add_fact("O(performTask(robot))")
kb.add_fact("B(robot, sensorActive)")

# Query the knowledge base
print(f"Total rules: {len(kb.get_all_rules())}")
print(f"Total facts: {len(kb.get_all_facts())}")

# Query for specific patterns
obligations = kb.query("O(*)")
print(f"Found {len(obligations)} obligation(s)")

beliefs = kb.query("B(robot, *)")
print(f"Found {len(beliefs)} belief(s) of robot")
```

**What just happened?**
- Created a knowledge base
- Added logical rules and facts
- Queried the knowledge base
- Found specific patterns

---

## 🎯 Common Use Cases

### Use Case 1: Robot Task Planning

```python
from ipfs_datasets_py.logic.CEC.native import DCECContainer
from ipfs_datasets_py.logic.CEC.native.prover_core import TheoremProver

# Create container
container = DCECContainer()

# Define robot obligations
container.create_obligation("robot", "cleanRoom")
container.create_obligation("robot", "reportStatus")

# Define robot beliefs
container.create_belief("robot", "roomIsDirty")
container.create_belief("robot", "batteryLow")

# Create prover with rules
prover = TheoremProver()
prover.add_axiom("O(cleanRoom(robot)) ∧ B(robot, roomIsDirty) → I(robot, startCleaning)")
prover.add_axiom("B(robot, batteryLow) → I(robot, recharge)")

# Check what robot should intend to do
print("Robot should clean:", prover.prove("I(robot, startCleaning)").is_proven)
print("Robot should recharge:", prover.prove("I(robot, recharge)").is_proven)
```

### Use Case 2: Legal Contract Analysis

```python
from ipfs_datasets_py.logic.CEC.native.nl_converter import NaturalLanguageConverter
from ipfs_datasets_py.logic.CEC.native.dcec_knowledge_base import DCECKnowledgeBase

# Convert legal text to logic
converter = NaturalLanguageConverter()
kb = DCECKnowledgeBase()

legal_clauses = [
    "The contractor must complete the project by December 31st",
    "The contractor is permitted to subcontract work",
    "The client must pay within 30 days of invoice",
    "The contractor knows the project requirements"
]

for clause in legal_clauses:
    dcec = converter.english_to_dcec(clause)
    kb.add_fact(dcec)
    print(f"Added: {dcec}")

# Query obligations
obligations = kb.query("O(*)")
print(f"\nContract obligations: {obligations}")

# Query permissions
permissions = kb.query("P(*)")
print(f"Contract permissions: {permissions}")
```

### Use Case 3: Multi-Agent Reasoning

```python
from ipfs_datasets_py.logic.CEC.native import DCECContainer
from ipfs_datasets_py.logic.CEC.native.prover_core import TheoremProver

# Model multiple agents
container = DCECContainer()

# Agent 1: Robot
container.create_belief("robot", "taskComplete")
container.create_intention("robot", "reportToHuman")

# Agent 2: Human supervisor
container.create_belief("human", "robotReported")
container.create_knowledge("human", "taskWasSuccessful")

# Agent 3: System
container.create_obligation("system", "logAllEvents")

# Prove that knowledge is shared
prover = TheoremProver()
prover.add_axiom("B(robot, taskComplete) ∧ I(robot, reportToHuman) → B(human, taskComplete)")
prover.add_axiom("B(human, taskComplete) → K(human, taskComplete)")

result = prover.prove("K(human, taskComplete)")
print(f"Human knows task is complete: {result.is_proven}")
```

### Use Case 4: Event Calculus Reasoning

```python
from ipfs_datasets_py.logic.CEC.native.prover_core import TheoremProver

# Model temporal events
prover = TheoremProver()

# Define events and their effects
prover.add_axiom("Happens(turnOnLight, t1)")
prover.add_axiom("Initiates(turnOnLight, lightOn, t1)")
prover.add_axiom("¬HoldsAt(lightOn, t0)")
prover.add_axiom("t0 < t1 < t2")

# Prove light state at different times
print("Light on at t0?", prover.prove("HoldsAt(lightOn, t0)").is_proven)  # False
print("Light on at t2?", prover.prove("HoldsAt(lightOn, t2)").is_proven)  # True
```

---

## 🔧 Troubleshooting

### Issue 1: Import Error

**Error:**
```
ModuleNotFoundError: No module named 'ipfs_datasets_py'
```

**Solution:**
```bash
# Make sure you installed the package
pip install -e .

# Or check your Python path
export PYTHONPATH=/path/to/ipfs_datasets_py:$PYTHONPATH
```

### Issue 2: Python Version

**Error:**
```
SyntaxError: invalid syntax (type hints)
```

**Solution:**
```bash
# Check Python version (must be 3.12+)
python --version

# Use correct Python version
python3.12 -m pip install -e .
```

### Issue 3: Test Failures

**Error:**
```
pytest: command not found
```

**Solution:**
```bash
# Install test dependencies
pip install -e ".[test]"

# Or install pytest directly
pip install pytest pytest-cov
```

### Issue 4: Proof Not Working

**Problem:** Theorem not proving as expected

**Solution:**
```python
# Enable debug mode
prover = TheoremProver(debug=True)

# Check axioms
print("Axioms:", prover.axioms)

# Check proof steps
result = prover.prove("B")
for step in result.proof_steps:
    print(f"Step: {step}")
```

---

## 🚀 Next Steps

### 1. Read Full Documentation

- **[CEC_SYSTEM_GUIDE.md](./CEC_SYSTEM_GUIDE.md)** - Comprehensive system guide
- **[STATUS.md](./STATUS.md)** - Current implementation status
- **[API_REFERENCE.md](./API_REFERENCE.md)** - Complete API documentation (coming soon)

### 2. Explore Examples

```bash
# Find example scripts
find ipfs_datasets_py/logic/CEC -name "*demo*.py"
find ipfs_datasets_py/logic/CEC -name "*example*.py"

# Run an example
python ipfs_datasets_py/logic/CEC/native/dcec_core.py
```

### 3. Run Tests

```bash
# Run all CEC tests
pytest tests/unit_tests/logic/CEC/ -v

# Run with coverage
pytest tests/unit_tests/logic/CEC/ --cov=ipfs_datasets_py.logic.CEC

# Run specific test file
pytest tests/unit_tests/logic/CEC/native/test_dcec_core.py -v
```

### 4. Explore Advanced Features

#### Modal Tableaux
```python
from ipfs_datasets_py.logic.CEC.native.modal_tableaux import ModalTableaux

tableaux = ModalTableaux()
result = tableaux.check_satisfiability("□(A → B) ∧ □A")
print(f"Satisfiable: {result.is_satisfiable}")
```

#### Shadow Prover
```python
from ipfs_datasets_py.logic.CEC.native.shadow_prover import ShadowProver

shadow = ShadowProver()
result = shadow.prove_with_shadow("A → B", ["A"])
print(f"Proven: {result.is_proven}")
```

#### Grammar Engine
```python
from ipfs_datasets_py.logic.CEC.native.grammar_engine import GrammarEngine

grammar = GrammarEngine()
parse_tree = grammar.parse("The robot must clean the room")
print(f"Parse tree: {parse_tree}")
```

### 5. Integrate with Your Project

```python
# Example: Add CEC to your application
from ipfs_datasets_py.logic.CEC.native import DCECContainer
from ipfs_datasets_py.logic.CEC.native.prover_core import TheoremProver

class MyApplication:
    def __init__(self):
        self.cec = DCECContainer()
        self.prover = TheoremProver()
    
    def add_rule(self, rule: str):
        """Add logical rule"""
        self.prover.add_axiom(rule)
    
    def check_obligation(self, agent: str, action: str) -> bool:
        """Check if agent has obligation"""
        formula = f"O({action}({agent}))"
        return formula in self.cec.statements
    
    def prove_consequence(self, conclusion: str) -> bool:
        """Prove logical consequence"""
        return self.prover.prove(conclusion).is_proven

# Use it
app = MyApplication()
app.add_rule("O(performTask(robot)) → I(robot, startTask)")
print("Has obligation:", app.check_obligation("robot", "performTask"))
```

### 6. Join the Community

- **Report Issues:** [GitHub Issues](https://github.com/endomorphosis/ipfs_datasets_py/issues)
- **Contribute:** See [DEVELOPER_GUIDE.md](./DEVELOPER_GUIDE.md) (coming soon)
- **Discuss:** [GitHub Discussions](https://github.com/endomorphosis/ipfs_datasets_py/discussions)

---

## 📊 Performance Tips

### Tip 1: Use Proof Caching

```python
# Proof caching is enabled by default
prover = TheoremProver(enable_cache=True)

# First proof: 50ms
result1 = prover.prove("B")

# Cached proof: 0.05ms (100x faster!)
result2 = prover.prove("B")
```

### Tip 2: Batch Operations

```python
# Add multiple axioms at once
prover.add_axioms([
    "A → B",
    "B → C",
    "C → D"
])

# Better than adding one by one
```

### Tip 3: Use Type Hints

```python
from typing import List
from ipfs_datasets_py.logic.CEC.native import DCECFormula

def process_formulas(formulas: List[DCECFormula]) -> None:
    """Type hints enable IDE autocomplete and error checking"""
    for formula in formulas:
        print(formula.to_string())
```

---

## 🎓 Learning Resources

### Beginner Level
1. **This QUICKSTART.md** - You're reading it!
2. **[CEC README](../../../ipfs_datasets_py/logic/CEC/README.md)** - Overview and introduction
3. **[CEC_SYSTEM_GUIDE.md](./CEC_SYSTEM_GUIDE.md)** sections 1-4

### Intermediate Level
4. **[CEC_SYSTEM_GUIDE.md](./CEC_SYSTEM_GUIDE.md)** sections 5-7
5. **[API_REFERENCE.md](./API_REFERENCE.md)** - Complete API (coming soon)
6. **Test files** in `tests/unit_tests/logic/CEC/` - Real examples

### Advanced Level
7. **[DEVELOPER_GUIDE.md](./DEVELOPER_GUIDE.md)** - Internals (coming soon)
8. **Source code** in `ipfs_datasets_py/logic/CEC/native/`
9. **Planning documents** - Architecture and design

---

## 💡 Key Concepts Summary

### Deontic Logic
- **O(φ)** - Obligation: "must do φ"
- **P(φ)** - Permission: "allowed to do φ"
- **F(φ)** - Forbidden: "must not do φ"

### Cognitive Logic
- **B(agent, φ)** - Belief: "agent believes φ"
- **K(agent, φ)** - Knowledge: "agent knows φ"
- **I(agent, φ)** - Intention: "agent intends φ"

### Temporal Logic
- **□(φ)** - Necessary: "always φ"
- **◊(φ)** - Possible: "eventually φ"
- **X(φ)** - Next: "φ in next state"

### Event Calculus
- **Happens(e, t)** - Event e at time t
- **HoldsAt(f, t)** - Fluent f at time t
- **Initiates(e, f, t)** - Event e starts f
- **Terminates(e, f, t)** - Event e ends f

---

## ✅ Congratulations!

You've completed the CEC Quick Start! You now know how to:

- ✅ Install and set up CEC
- ✅ Create DCEC containers
- ✅ Convert natural language to logic
- ✅ Prove theorems automatically
- ✅ Build knowledge bases
- ✅ Use CEC in your projects

**Ready for more?** Continue to [CEC_SYSTEM_GUIDE.md](./CEC_SYSTEM_GUIDE.md) for comprehensive documentation.

---

**Need Help?**
- 📖 [Full Documentation](./CEC_SYSTEM_GUIDE.md)
- 📊 [Implementation Status](./STATUS.md)
- 🐛 [Report Issues](https://github.com/endomorphosis/ipfs_datasets_py/issues)
- 💬 [Discussions](https://github.com/endomorphosis/ipfs_datasets_py/discussions)

---

**Last Updated:** 2026-02-18  
**Estimated Time:** 5 minutes  
**Difficulty:** Beginner
