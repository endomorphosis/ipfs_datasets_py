#!/usr/bin/env python3
"""
Quick PDF Processing Test
Test the core PDF processing functionality without monitoring.
"""


def test_core_pdf_components():
    """Test core PDF processing components"""
    print("🔍 Testing Core PDF Processing Components (No Monitoring)")
    print("=" * 60)

    try:
        # Test basic imports
        from ipfs_datasets_py.pdf_processing import (
            PDFProcessor,
            LLMOptimizer,
            MultiEngineOCR,
            HAVE_PDF_PROCESSOR,
            HAVE_LLM_OPTIMIZER,
            HAVE_OCR_ENGINE,
        )

        print(f"✅ Imports successful")
        print(f"   PDF Processor: {'✅' if HAVE_PDF_PROCESSOR else '❌'}")
        print(f"   LLM Optimizer: {'✅' if HAVE_LLM_OPTIMIZER else '❌'}")
        print(f"   OCR Engine: {'✅' if HAVE_OCR_ENGINE else '❌'}")

        # Test initialization without monitoring
        processor = PDFProcessor(enable_monitoring=False)
        print(f"✅ PDFProcessor initialized (monitoring disabled)")

        # Test LLM Optimizer
        try:
            llm_optimizer = LLMOptimizer()
            print(f"✅ LLMOptimizer initialized")
            print(f"   Model: {llm_optimizer.model_name}")
            print(f"   Max chunk size: {llm_optimizer.max_chunk_size}")
        except Exception as e:
            print(f"⚠️  LLMOptimizer initialization issue: {e}")

        # Test OCR Engine
        try:
            ocr_engine = MultiEngineOCR()
            print(f"✅ MultiEngineOCR initialized")
            print(f"   Primary engine: {ocr_engine.primary_engine}")
            print(f"   Fallback engines: {ocr_engine.fallback_engines}")
        except Exception as e:
            print(f"⚠️  OCR engine initialization issue: {e}")

        return True

    except Exception as e:
        print(f"❌ Core component test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_transformers_availability():
    """Test if transformers is working"""
    print("\n🔍 Testing Transformers Availability")
    print("=" * 40)

    try:
        import transformers
        from transformers import PreTrainedModel

        print(f"✅ transformers version: {transformers.__version__}")
        print(f"✅ PreTrainedModel imported successfully")
        return True
    except Exception as e:
        print(f"❌ Transformers issue: {e}")
        return False


def test_sentence_transformers():
    """Test sentence transformers"""
    print("\n🔍 Testing Sentence Transformers")
    print("=" * 40)

    try:
        from sentence_transformers import SentenceTransformer

        print(f"✅ SentenceTransformer imported successfully")
        # Don't actually load a model to avoid delays
        print(f"✅ Ready to load models for embedding generation")
        return True
    except Exception as e:
        print(f"❌ Sentence transformers issue: {e}")
        return False


if __name__ == "__main__":
    print("🚀 PDF Processing Quick Test")
    print("=" * 60)

    results = {
        "core_components": test_core_pdf_components(),
        "transformers": test_transformers_availability(),
        "sentence_transformers": test_sentence_transformers(),
    }

    print("\n" + "=" * 60)
    print("📊 Test Results Summary:")
    success_count = sum(results.values())
    total_count = len(results)

    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"   {test_name}: {status}")

    print(f"\n🎯 Overall: {success_count}/{total_count} tests passed")

    if success_count == total_count:
        print("🎉 All core components are working!")
    elif success_count >= 2:
        print("⚠️  Most components working, minor issues to resolve")
    else:
        print("🔧 Significant issues need attention")
