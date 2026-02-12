#!/usr/bin/env python3
"""
Demonstration of Native CEC Integration

Shows how the CEC wrappers seamlessly use native Python 3 implementations
with automatic fallback to Python 2 submodules.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from ipfs_datasets_py.logic.CEC import (
    DCECLibraryWrapper,
    TalosWrapper,
    EngDCECWrapper
)


def print_section(title: str):
    """Print a section header."""
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}\n")


def demonstrate_dcec_wrapper():
    """Demonstrate DCEC Library wrapper with native integration."""
    print_section("DCEC Library Wrapper - Native Integration")
    
    # Create wrapper (prefers native by default)
    print("Creating DCECLibraryWrapper (use_native=True by default)...")
    wrapper = DCECLibraryWrapper()
    
    # Initialize
    print("Initializing...")
    success = wrapper.initialize()
    print(f"  Initialization: {'SUCCESS' if success else 'FAILED'}")
    
    if success:
        # Get backend info
        backend_info = wrapper.get_backend_info()
        print(f"\nBackend Information:")
        print(f"  Using native: {backend_info['is_native']}")
        print(f"  Backend type: {backend_info['backend']}")
        print(f"  Preference: use_native={backend_info['use_native_preference']}")
        
        # Show repr
        print(f"\nWrapper representation: {wrapper}")
        
        # Try adding statement (if native available)
        if backend_info['is_native']:
            print(f"\n✓ Native Python 3 backend is active!")
            print(f"  Zero Python 2 dependencies")
            print(f"  Full type hints and modern features")
        else:
            print(f"\n→ Using Python 2 submodule fallback")
            print(f"  Native not available on this system")
    
    # Show force submodule mode
    print(f"\n{'─'*70}")
    print("Creating DCECLibraryWrapper with use_native=False...")
    wrapper_submodule = DCECLibraryWrapper(use_native=False)
    success = wrapper_submodule.initialize()
    
    if success:
        backend_info = wrapper_submodule.get_backend_info()
        print(f"  Backend type: {backend_info['backend']}")
        print(f"  (Forced submodule mode)")


def demonstrate_talos_wrapper():
    """Demonstrate Talos wrapper with native integration."""
    print_section("Talos Theorem Prover Wrapper - Native Integration")
    
    # Create wrapper
    print("Creating TalosWrapper (use_native=True by default)...")
    wrapper = TalosWrapper()
    
    # Initialize
    print("Initializing...")
    success = wrapper.initialize()
    print(f"  Initialization: {'SUCCESS' if success else 'FAILED'}")
    
    if success:
        # Get backend info
        backend_info = wrapper.get_backend_info()
        print(f"\nBackend Information:")
        print(f"  Using native: {backend_info['is_native']}")
        print(f"  Backend type: {backend_info['backend']}")
        
        # Show repr
        print(f"\nWrapper representation: {wrapper}")
        
        # Try a simple proof if native
        if backend_info['is_native']:
            print(f"\n✓ Native Python 3 theorem prover is active!")
            print(f"  Forward chaining with inference rules")
            print(f"  Modus Ponens, Simplification, Conjunction")
            
            # Try a proof
            print(f"\nAttempting simple proof:")
            print(f"  Goal: Q")
            print(f"  Axioms: P, P→Q")
            
            from ipfs_datasets_py.logic.CEC.native import (
                AtomicFormula, Predicate, ConnectiveFormula, LogicalConnective
            )
            
            # Create simple formulas
            pred_p = Predicate("P", 0)
            pred_q = Predicate("Q", 0)
            p_formula = AtomicFormula(pred_p, [])
            q_formula = AtomicFormula(pred_q, [])
            p_implies_q = ConnectiveFormula(
                LogicalConnective.IMPLIES,
                [p_formula, q_formula]
            )
            
            # Prove
            result = wrapper.prove_theorem(
                conjecture=q_formula,
                axioms=[p_formula, p_implies_q]
            )
            
            print(f"  Result: {result.result.value}")
            if result.result.name == "PROVED":
                print(f"  ✓ Proof successful via Modus Ponens!")
        else:
            print(f"\n→ Using Talos/SPASS submodule fallback")


def demonstrate_engdcec_wrapper():
    """Demonstrate Eng-DCEC wrapper with native integration."""
    print_section("Eng-DCEC NL Converter Wrapper - Native Integration")
    
    # Create wrapper
    print("Creating EngDCECWrapper (use_native=True by default)...")
    wrapper = EngDCECWrapper()
    
    # Initialize
    print("Initializing...")
    success = wrapper.initialize()
    print(f"  Initialization: {'SUCCESS' if success else 'FAILED'}")
    
    if success:
        # Get backend info
        backend_info = wrapper.get_backend_info()
        print(f"\nBackend Information:")
        print(f"  Using native: {backend_info['is_native']}")
        print(f"  Backend type: {backend_info['backend']}")
        
        # Show repr
        print(f"\nWrapper representation: {wrapper}")
        
        # Try conversions if native
        if backend_info['is_native']:
            print(f"\n✓ Native Python 3 NL converter is active!")
            print(f"  Pattern-based English ↔ DCEC conversion")
            print(f"  15+ supported patterns")
            
            # Try conversions
            print(f"\nTesting conversions:")
            
            test_sentences = [
                "the agent must act",
                "the robot may move",
                "it is forbidden to delete",
                "the system believes that the goal is achieved"
            ]
            
            for sentence in test_sentences:
                result = wrapper.convert_to_dcec(sentence)
                if result.success:
                    print(f"  ✓ '{sentence}'")
                    print(f"    → {result.dcec_formula}")
                else:
                    print(f"  ✗ '{sentence}' (not recognized)")
        else:
            print(f"\n→ Using Eng-DCEC/GF submodule fallback")


def demonstrate_cross_wrapper():
    """Demonstrate all wrappers working together."""
    print_section("Cross-Wrapper Integration")
    
    print("Initializing all three wrappers...")
    
    dcec = DCECLibraryWrapper()
    talos = TalosWrapper()
    eng = EngDCECWrapper()
    
    dcec_ok = dcec.initialize()
    talos_ok = talos.initialize()
    eng_ok = eng.initialize()
    
    print(f"  DCEC Library: {'✓' if dcec_ok else '✗'}")
    print(f"  Talos Prover: {'✓' if talos_ok else '✗'}")
    print(f"  Eng-DCEC Converter: {'✓' if eng_ok else '✗'}")
    
    if all([dcec_ok, talos_ok, eng_ok]):
        print(f"\nBackend Summary:")
        
        backends = {
            "DCEC": dcec.get_backend_info()["backend"],
            "Talos": talos.get_backend_info()["backend"],
            "Eng-DCEC": eng.get_backend_info()["backend"]
        }
        
        for name, backend in backends.items():
            symbol = "🐍" if backend == "native_python3" else "🔙"
            print(f"  {symbol} {name:12} → {backend}")
        
        # Count native vs submodule
        native_count = sum(1 for b in backends.values() if b == "native_python3")
        print(f"\nNative backends: {native_count}/3")
        
        if native_count == 3:
            print(f"✓ All components using native Python 3 implementation!")
            print(f"  Zero Python 2 dependencies")
            print(f"  Maximum performance and modern features")
        elif native_count > 0:
            print(f"→ Mixed mode: {native_count} native, {3-native_count} submodule")
            print(f"  Graceful degradation working correctly")
        else:
            print(f"→ All using submodule fallback")
            print(f"  Native implementations not available")


def main():
    """Run all demonstrations."""
    print(f"""
{'='*70}
  Native CEC Integration Demonstration
{'='*70}

This demonstrates how CEC wrappers seamlessly integrate native Python 3
implementations with automatic fallback to Python 2 submodules.

Key Features:
  • Transparent integration - no code changes needed
  • Automatic backend selection - native preferred
  • Graceful fallback - submodule if native unavailable
  • Configurable - can force submodule if needed
  • Backend inspection - know what you're using
    """)
    
    try:
        demonstrate_dcec_wrapper()
        demonstrate_talos_wrapper()
        demonstrate_engdcec_wrapper()
        demonstrate_cross_wrapper()
        
        print_section("Summary")
        print("✓ All demonstrations completed successfully!")
        print("\nThe CEC framework provides:")
        print("  1. Native Python 3 implementations (preferred)")
        print("  2. Python 2 submodule fallback (automatic)")
        print("  3. Zero breaking changes to existing code")
        print("  4. Full backward compatibility")
        print("  5. Transparent upgrade path")
        
    except Exception as e:
        print(f"\n❌ Error during demonstration: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
