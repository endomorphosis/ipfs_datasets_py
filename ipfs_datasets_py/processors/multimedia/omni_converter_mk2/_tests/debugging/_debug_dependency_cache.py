#!/usr/bin/env python3

import sys
sys.path.insert(0, '/home/kylerose1946/omni_converter_mk2')

from unittest.mock import patch, MagicMock
from core.content_extractor.processors.processor_factory import dependency_cache, _make_processor

print("Original dependency_cache:", type(dependency_cache))
print("Available attributes:", dir(dependency_cache))

# Test the correct patch target
try:
    with patch('core.content_extractor.processors.factory.dependency_cache') as mock_cache:
        mock_cache.__getitem__.side_effect = lambda key: MagicMock() if key == "openpyxl" else (_ for _ in ()).throw(KeyError(f"Not found: {key}"))
        print("✓ Patch works!")
        
        # Test basic resources
        resources = {
            "supported_formats": {"xlsx"},
            "processor_name": "test",
            "dependencies": {"openpyxl": MagicMock()},
            "critical_resources": ["extract_text"],
            "optional_resources": [],
            "logger": MagicMock(),
            "configs": MagicMock(),
        }
        
        processor = _make_processor(resources)
        print("✓ Processor created:", type(processor))
        
except Exception as e:
    print("✗ Patch failed:", e)

# Test alternative patch targets
alternative_targets = [
    'dependencies.dependencies',
    'core.content_extractor.processors.factory.dependencies',
    'factory.dependency_cache'
]

for target in alternative_targets:
    try:
        with patch(target) as mock_dep:
            print(f"✓ Alternative target works: {target}")
            break
    except Exception as e:
        print(f"✗ Alternative target failed: {target} - {e}")

# Let's also check the module structure
import core.content_extractor.processors.processor_factory as factory_module
print("\nFactory module attributes:")
for attr in dir(factory_module):
    if not attr.startswith('_'):
        print(f"  {attr}: {type(getattr(factory_module, attr))}")

# Check if dependency_cache is really there
if hasattr(factory_module, 'dependency_cache'):
    print(f"\n✓ dependency_cache found: {type(factory_module.dependency_cache)}")
else:
    print("\n✗ dependency_cache not found in factory module")