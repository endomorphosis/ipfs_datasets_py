# TODO - Omni Converter mk2

## Critical Issues to Fix

### 1. Missing Dependencies in Handler Resources
- [ ] Add `can_handle` to TextHandler resources in factory.py
- [ ] Add `can_handle` to ApplicationHandler resources in factory.py  
- [ ] Add `can_handle` to AudioHandler resources in factory.py
- [ ] Add `can_handle` to VideoHandler resources in factory.py
- [ ] Verify all handlers have consistent resource requirements

### 2. Processor System is Broken
- [ ] None of the processors are loading (all returning mocks)
- [ ] Need to create at least ONE working processor for text files
- [ ] Fix the processor factory import system
- [ ] Remove or fix the complex processor hierarchy (by_ability, by_mime_type, etc.)

### 3. Fix Import/Module Structure
- [ ] content_extractor/__init__.py is calling make_content_extractor() at module level (causing import loops)
- [ ] Too many circular dependencies between modules
- [ ] types_.py has incomplete type definitions

### 4. Get ONE Format Working End-to-End
- [ ] Pick plaintext (.txt) as the simplest format
- [ ] Create a simple plaintext processor that just reads the file
- [ ] Wire it up through the handler system
- [ ] Make sure it works from CLI to output
- [ ] Write a test that passes

### 5. Testing Strategy
- [ ] All existing tests expect old architecture
- [ ] Need to create new tests using red-green-refactor
- [ ] Start with integration test for one file type
- [ ] Delete or quarantine old tests that don't match current architecture

## Simplification Opportunities

### 1. Processor Architecture
- Current: Complex 4-tier system (by_ability, by_mime_type, dependency_modules, fallbacks)
- Proposed: Single processor per file type, with optional fallbacks

### 2. Handler Pattern  
- Current: IoC with complex resource injection
- Consider: Simple classes with direct dependencies

### 3. Too Many Abstraction Layers
- Main → Interfaces → Core → ContentExtractor → Handlers → Processors → DependencyModules
- Could be: Main → Pipeline → FileHandler → Output

## Next Steps Priority Order

1. **Fix the immediate KeyError** - Add missing `can_handle` to handler resources
2. **Get plaintext files working** - Simplest possible implementation
3. **Create one passing test** - Proves the system can work
4. **Document what actually works** - Update architecture docs
5. **Incrementally add complexity** - One format at a time

## Questions to Answer

1. Why are all processors returning mocks?
2. Is the 4-tier processor system necessary?
3. Can we simplify the IoC pattern?
4. Which parts of the old architecture are worth keeping?
5. What's the actual MVP - just text extraction?
