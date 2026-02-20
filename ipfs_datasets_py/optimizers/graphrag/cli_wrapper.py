"""CLI wrapper for GraphRAG Optimizer.

Provides command-line interface for:
- Generating ontologies from documents
- Optimizing knowledge graphs
- Validating ontology consistency
- Query optimization
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


def _safe_resolve(path_str: str, *, must_exist: bool = False) -> Path:
    """Resolve a user-supplied path, guarding against path-traversal attacks.

    Args:
        path_str: Raw path string from CLI args.
        must_exist: If True, raise ``FileNotFoundError`` when the path does not exist.

    Returns:
        Resolved absolute :class:`~pathlib.Path`.

    Raises:
        ValueError: If the resolved path escapes a safe root (e.g. ``/etc``, ``/proc``).
        FileNotFoundError: If *must_exist* is True and the path does not exist.
    """
    resolved = Path(path_str).resolve()
    _FORBIDDEN_PREFIXES = (Path('/proc'), Path('/sys'), Path('/dev'), Path('/etc'))
    for forbidden in _FORBIDDEN_PREFIXES:
        try:
            resolved.relative_to(forbidden)
            raise ValueError(f"Path '{path_str}' resolves into restricted area: {forbidden}")
        except ValueError as exc:
            if 'restricted area' in str(exc):
                raise
    if must_exist and not resolved.exists():
        raise FileNotFoundError(f"Path not found: {resolved}")
    return resolved

try:
    from ipfs_datasets_py.optimizers.graphrag import (
        OntologyGenerator,
        OntologyCritic,
        OntologyMediator,
        OntologyOptimizer,
        OntologySession,
        OntologyHarness,
        LogicValidator,
        OntologyGenerationContext,
        ExtractionStrategy,
        DataType,
    )
    GRAPHRAG_AVAILABLE = True
except ImportError:
    GRAPHRAG_AVAILABLE = False


class GraphRAGOptimizerCLI:
    """Command-line interface for GraphRAG Optimizer."""
    
    def __init__(self):
        """Initialize CLI."""
        if not GRAPHRAG_AVAILABLE:
            raise ImportError("GraphRAG Optimizer not available")
    
    def create_parser(self) -> argparse.ArgumentParser:
        """Create argument parser.
        
        Returns:
            Configured ArgumentParser
        """
        parser = argparse.ArgumentParser(
            prog='optimizers --type graphrag',
            description='GraphRAG Optimizer - Knowledge graph and ontology optimization',
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
Examples:
  # Generate ontology from document
  %(prog)s generate --input document.pdf --domain legal --output ontology.owl
  
  # Generate with specific strategy
  %(prog)s generate --input data.json --strategy hybrid --output kg.owl
  
  # Optimize existing knowledge graph
  %(prog)s optimize --input ontology.owl --cycles 5 --output optimized.owl
  
  # Validate ontology consistency
  %(prog)s validate --input ontology.owl --check-consistency
  
  # Optimize query
  %(prog)s query --ontology my_kg.owl --query "climate change" --optimize
  
  # Show status
  %(prog)s status

    # Show query optimizer health snapshot
    %(prog)s health --window 100
""")
        
        subparsers = parser.add_subparsers(dest='command', help='Commands', required=True)
        
        # generate command
        generate_parser = subparsers.add_parser(
            'generate',
            help='Generate ontology from documents/data'
        )
        generate_parser.add_argument(
            '--input', '-i',
            required=True,
            help='Input file (PDF, JSON, text, etc.)'
        )
        generate_parser.add_argument(
            '--output', '-o',
            help='Output ontology file (OWL, RDF, JSON)'
        )
        generate_parser.add_argument(
            '--domain',
            choices=['legal', 'scientific', 'medical', 'general'],
            default='general',
            help='Domain context'
        )
        generate_parser.add_argument(
            '--strategy',
            choices=['rule_based', 'neural', 'hybrid'],
            default='hybrid',
            help='Extraction strategy'
        )
        generate_parser.add_argument(
            '--format',
            choices=['owl', 'rdf', 'json'],
            default='owl',
            help='Output format'
        )
        
        # optimize command
        optimize_parser = subparsers.add_parser(
            'optimize',
            help='Optimize knowledge graph structure and quality'
        )
        optimize_parser.add_argument(
            '--input', '-i',
            required=True,
            help='Input ontology file'
        )
        optimize_parser.add_argument(
            '--cycles',
            type=int,
            default=3,
            help='Number of optimization cycles'
        )
        optimize_parser.add_argument(
            '--parallel',
            action='store_true',
            help='Run optimization in parallel'
        )
        optimize_parser.add_argument(
            '--output', '-o',
            help='Output optimized ontology'
        )
        optimize_parser.add_argument(
            '--target',
            choices=['structure', 'consistency', 'coverage', 'all'],
            default='all',
            help='Optimization target'
        )
        
        # validate command
        validate_parser = subparsers.add_parser(
            'validate',
            help='Validate ontology consistency and quality'
        )
        validate_parser.add_argument(
            '--input', '-i',
            required=True,
            help='Input ontology file'
        )
        validate_parser.add_argument(
            '--check-consistency',
            action='store_true',
            help='Check logical consistency'
        )
        validate_parser.add_argument(
            '--check-coverage',
            action='store_true',
            help='Check domain coverage'
        )
        validate_parser.add_argument(
            '--check-clarity',
            action='store_true',
            help='Check relationship clarity'
        )
        validate_parser.add_argument(
            '--output', '-o',
            help='Output validation report'
        )
        
        # query command
        query_parser = subparsers.add_parser(
            'query',
            help='Query optimization for RAG systems'
        )
        query_parser.add_argument(
            '--ontology',
            required=True,
            help='Knowledge graph/ontology file'
        )
        query_parser.add_argument(
            '--query',
            required=True,
            help='Query string'
        )
        query_parser.add_argument(
            '--optimize',
            action='store_true',
            help='Optimize query performance'
        )
        query_parser.add_argument(
            '--explain',
            action='store_true',
            help='Explain query execution'
        )
        query_parser.add_argument(
            '--output', '-o',
            help='Output results file'
        )
        
        # status command
        status_parser = subparsers.add_parser(
            'status',
            help='Show optimizer status and capabilities'
        )

        # health command
        health_parser = subparsers.add_parser(
            'health',
            help='Show query optimizer health snapshot'
        )
        health_parser.add_argument(
            '--window',
            type=int,
            default=100,
            help='Number of recent sessions to use for error-rate calculation'
        )
        health_parser.add_argument(
            '--output', '-o',
            help='Optional output JSON file path'
        )
        
        return parser

    def _read_text(self, path: Path) -> str:
        return path.read_text(encoding="utf-8", errors="replace")

    def _load_json(self, path: Path) -> Any:
        return json.loads(self._read_text(path))

    def _load_ontology_json(self, path: Path) -> Dict[str, Any]:
        """Load a JSON ontology dict.

        Expected keys: 'entities' and 'relationships'.
        """
        obj = self._load_json(path)
        if not isinstance(obj, dict):
            raise ValueError("Ontology JSON must be a JSON object")
        if "entities" not in obj or "relationships" not in obj:
            raise ValueError("Ontology JSON must include 'entities' and 'relationships'")
        if not isinstance(obj.get("entities"), list) or not isinstance(obj.get("relationships"), list):
            raise ValueError("Ontology JSON 'entities' and 'relationships' must be lists")
        return obj
    
    def cmd_generate(self, args: argparse.Namespace) -> int:
        """Generate ontology from data.
        
        Args:
            args: Command arguments
            
        Returns:
            Exit code
        """
        print(f"🏗️  Generating ontology from: {args.input}")
        print(f"   Domain: {args.domain}")
        print(f"   Strategy: {args.strategy}")
        print(f"   Format: {args.format}\n")
        
        input_path = _safe_resolve(args.input, must_exist=True)
        if not input_path.exists():
            print(f"❌ Input file not found: {args.input}")
            return 1
        
        try:
            data = self._read_text(input_path)
            
            # Create generator
            generator = OntologyGenerator()
            
            # Map strategy
            strategy_map = {
                'rule_based': ExtractionStrategy.RULE_BASED,
                'neural': ExtractionStrategy.NEURAL,
                'hybrid': ExtractionStrategy.HYBRID,
            }
            
            # Create context
            context = OntologyGenerationContext(
                data_source=str(input_path),
                data_type=DataType.TEXT,
                domain=args.domain,
                extraction_strategy=strategy_map[args.strategy],
            )
            
            # Generate ontology
            print("⏳ Generating ontology...")
            ontology = generator.generate_ontology(data, context)
            
            print(f"✅ Generated ontology")
            print(f"   Entities: {len(ontology.get('entities', []))}")
            print(f"   Relationships: {len(ontology.get('relationships', []))}")
            confidence = ontology.get('metadata', {}).get('confidence', None)
            if isinstance(confidence, (int, float)):
                print(f"   Confidence: {confidence:.2f}")
            
            # Evaluate quality
            critic = OntologyCritic()
            score = critic.evaluate_ontology(ontology, context, data)
            print(f"   Quality score: {score.overall:.2f}")
            
            # Output results
            if args.output:
                output_data = {
                    'entities': ontology.get('entities', []),
                    'relationships': ontology.get('relationships', []),
                    'metadata': ontology.get('metadata', {}),
                    'quality_score': score.overall,
                }
                
                with open(args.output, 'w') as f:
                    json.dump(output_data, f, indent=2)
                print(f"📄 Saved to: {args.output}")
            
            return 0
            
        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()
            return 1
    
    def cmd_optimize(self, args: argparse.Namespace) -> int:
        """Optimize knowledge graph.
        
        Args:
            args: Command arguments
            
        Returns:
            Exit code
        """
        print(f"🚀 Optimizing knowledge graph")
        print(f"   Input: {args.input}")
        print(f"   Cycles: {args.cycles}")
        print(f"   Target: {args.target}")
        print(f"   Parallel: {args.parallel}\n")
        
        input_path = _safe_resolve(args.input, must_exist=True)
        if not input_path.exists():
            print(f"❌ Input file not found: {args.input}")
            return 1
        
        try:
            data = self._read_text(input_path)

            base_ontology: Optional[Dict[str, Any]] = None
            data_type = DataType.TEXT
            if input_path.suffix.lower() == ".json":
                try:
                    base_ontology = self._load_ontology_json(input_path)
                    data_type = DataType.STRUCTURED
                    # Use empty source data; the base ontology is the optimization target.
                    data = ""
                except Exception:
                    # Not an ontology JSON; treat as structured data input.
                    data_type = DataType.JSON

            generator = OntologyGenerator()
            mediator = OntologyMediator()
            critic = OntologyCritic()
            validator = LogicValidator()

            # Use session runner for best-effort optimization cycles.
            session = OntologySession(
                generator=generator,
                mediator=mediator,
                critic=critic,
                validator=validator,
                max_rounds=max(1, int(args.cycles)),
            )

            context = OntologyGenerationContext(
                data_source=str(input_path),
                data_type=data_type,
                domain="general",
                base_ontology=base_ontology,
                extraction_strategy=ExtractionStrategy.HYBRID,
                config={"target": args.target, "parallel": bool(args.parallel)},
            )

            print("⏳ Running optimization session...")
            result = session.run(data, context)

            if result.critic_score is None:
                raise RuntimeError(result.metadata.get("error", "optimization session failed"))

            print("\n✅ Optimization complete")
            print(f"   Quality score: {result.critic_score.overall:.2f}")
            if result.validation_result is not None:
                print(f"   Consistent: {'✓' if result.validation_result.is_consistent else '✗'}")
            print(f"   Rounds: {result.num_rounds}")

            if args.output:
                with open(args.output, "w") as f:
                    json.dump(
                        {
                            "ontology": result.ontology,
                            "critic_score": result.critic_score.to_dict(),
                            "validation": (
                                result.validation_result.to_dict()
                                if result.validation_result is not None
                                else None
                            ),
                            "num_rounds": result.num_rounds,
                            "converged": result.converged,
                            "time_elapsed": result.time_elapsed,
                            "metadata": result.metadata,
                        },
                        f,
                        indent=2,
                    )
                print(f"📄 Saved to: {args.output}")

            return 0

        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()
            return 1
    
    def cmd_validate(self, args: argparse.Namespace) -> int:
        """Validate ontology.
        
        Args:
            args: Command arguments
            
        Returns:
            Exit code
        """
        print(f"✓ Validating ontology: {args.input}\n")
        
        input_path = _safe_resolve(args.input, must_exist=True)
        if not input_path.exists():
            print(f"❌ Input file not found: {args.input}")
            return 1
        
        try:
            if input_path.suffix.lower() != ".json":
                raise ValueError("validate currently supports JSON ontology files only")

            ontology = self._load_ontology_json(input_path)
            validator = LogicValidator()
            critic = OntologyCritic()

            print("⏳ Validating...")

            report: Dict[str, Any] = {
                "input": str(input_path),
                "checks": {},
            }

            if args.check_consistency:
                consistency = validator.check_consistency(ontology)
                report["checks"]["consistency"] = consistency.to_dict()
                if consistency.is_consistent:
                    print("✅ Consistency check: PASSED")
                else:
                    print("❌ Consistency check: FAILED")
                    for c in consistency.contradictions[:10]:
                        print(f"   - {c}")

            if args.check_coverage or args.check_clarity:
                context = OntologyGenerationContext(
                    data_source=str(input_path),
                    data_type=DataType.STRUCTURED,
                    domain="general",
                )
                score = critic.evaluate_ontology(ontology, context, source_data=None)
                report["checks"]["quality"] = score.to_dict()
                if args.check_coverage:
                    print("✅ Coverage (completeness) score:", f"{score.completeness:.2f}")
                if args.check_clarity:
                    print("✅ Clarity score:", f"{score.clarity:.2f}")

            if not (args.check_consistency or args.check_coverage or args.check_clarity):
                # Default to running all checks if none explicitly requested.
                consistency = validator.check_consistency(ontology)
                context = OntologyGenerationContext(
                    data_source=str(input_path),
                    data_type=DataType.STRUCTURED,
                    domain="general",
                )
                score = critic.evaluate_ontology(ontology, context, source_data=None)
                report["checks"]["consistency"] = consistency.to_dict()
                report["checks"]["quality"] = score.to_dict()

                print("✅ Consistency:", "PASSED" if consistency.is_consistent else "FAILED")
                print("✅ Completeness:", f"{score.completeness:.2f}")
                print("✅ Clarity:", f"{score.clarity:.2f}")

            if args.output:
                with open(args.output, "w") as f:
                    json.dump(report, f, indent=2)
                print(f"\n📄 Report saved to: {args.output}")

            # Exit code: 0 only if consistency check passed when run.
            if "consistency" in report["checks"]:
                return 0 if report["checks"]["consistency"]["is_consistent"] else 2
            return 0

        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()
            return 1
    

    def cmd_query(self, args: argparse.Namespace) -> int:
        """Optimize query.

        Args:
            args: Command arguments

        Returns:
            Exit code
        """
        print("🔍 Query optimization")
        print(f"   Ontology: {args.ontology}")
        print(f"   Query: {args.query}")
        print()

        try:
            ontology_path = Path(args.ontology)
            if not ontology_path.exists():
                print(f"❌ Ontology file not found: {args.ontology}")
                return 1

            graph_info: Dict[str, Any] = {}
            if ontology_path.suffix.lower() == ".json":
                try:
                    graph_info = self._load_ontology_json(ontology_path)
                except Exception:
                    # Best-effort: not all JSON files are ontology dicts.
                    graph_info = {}

            from ipfs_datasets_py.optimizers.graphrag.query_optimizer import UnifiedGraphRAGQueryOptimizer

            optimizer = UnifiedGraphRAGQueryOptimizer(graph_info=graph_info, metrics_dir=None)

            # Build a minimal query dict. This command focuses on planning/optimization,
            # not executing retrieval.
            query_dict: Dict[str, Any] = {
                "query_text": args.query,
                "traversal": {"max_depth": 2},
                "entity_ids": [],
            }

            if args.optimize:
                print("⏳ Optimizing query plan...")

            plan = optimizer.optimize_query(query=query_dict, priority="normal", graph_processor=None)

            if args.optimize:
                print("✅ Query plan optimized")
                print(f"   Graph type: {plan.get('graph_type', 'unknown')}")
                budget = plan.get("budget")
                if isinstance(budget, dict):
                    print(
                        "   Budget(ms):",
                        f"vector={budget.get('vector_search_ms','?')}",
                        f"graph={budget.get('graph_traversal_ms','?')}",
                        f"rank={budget.get('ranking_ms','?')}"
                    )

            execution_plan: Optional[Dict[str, Any]] = None
            if args.explain:
                execution_plan = optimizer.get_execution_plan(query_dict, priority="normal", graph_processor=None)
                steps = execution_plan.get("execution_steps", []) if isinstance(execution_plan, dict) else []

                print()
                print("📋 Query execution plan:")
                if steps:
                    for idx, step in enumerate(steps, start=1):
                        name = step.get("name", f"step_{idx}")
                        desc = step.get("description", "")
                        print(f"  {idx}. {name}: {desc}")
                else:
                    print("  (no steps available)")

            if args.output:
                out = {
                    "ontology": str(ontology_path),
                    "query": args.query,
                    "optimized": bool(args.optimize),
                    "plan": plan,
                    "execution_plan": execution_plan,
                }
                with open(args.output, "w") as f:
                    json.dump(out, f, indent=2)

                print()
                print(f"📄 Saved to: {args.output}")

            return 0

        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()
            return 1

    def cmd_status(self, args: argparse.Namespace) -> int:
        """Show status.
        
        Args:
            args: Command arguments
            
        Returns:
            Exit code
        """
        print("📊 GraphRAG Optimizer Status\n")
        print("Version: 0.1.0")
        print("Status: ✓ Available\n")
        
        print("Capabilities:")
        print("  ✓ Ontology generation from multiple sources")
        print("  ✓ Knowledge graph optimization")
        print("  ✓ Logical consistency validation")
        print("  ✓ RAG query optimization")
        print("  ✓ Wikipedia integration")
        print("  ✓ SGD-based improvement cycles\n")
        
        print("Supported formats:")
        print("  • OWL (Web Ontology Language)")
        print("  • RDF (Resource Description Framework)")
        print("  • JSON (JSON-LD)")
        print("  • PDF document processing")
        print("  • Wikipedia data\n")
        
        print("Extraction strategies:")
        print("  • Rule-based (fast, deterministic)")
        print("  • Neural (AI-powered, flexible)")
        print("  • Hybrid (best of both)\n")
        
        return 0

    def cmd_health(self, args: argparse.Namespace) -> int:
        """Show health snapshot for query optimization metrics.

        Args:
            args: Command arguments

        Returns:
            Exit code
        """
        print("🩺 GraphRAG Query Optimizer Health")

        try:
            from ipfs_datasets_py.optimizers.graphrag.query_optimizer import QueryMetricsCollector

            collector = QueryMetricsCollector(track_resources=True)
            report = collector.get_health_check(window_size=args.window)

            print(json.dumps(report, indent=2))

            if args.output:
                output_path = _safe_resolve(args.output)
                with open(output_path, "w") as file_obj:
                    json.dump(report, file_obj, indent=2)
                print(f"\n📄 Saved to: {output_path}")

            return 0
        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()
            return 1
    
    def run(self, args: Optional[List[str]] = None) -> int:
        """Run CLI.
        
        Args:
            args: Command-line arguments
            
        Returns:
            Exit code
        """
        parser = self.create_parser()
        parsed_args = parser.parse_args(args)
        
        try:
            # Route to appropriate command
            if parsed_args.command == 'generate':
                return self.cmd_generate(parsed_args)
            elif parsed_args.command == 'optimize':
                return self.cmd_optimize(parsed_args)
            elif parsed_args.command == 'validate':
                return self.cmd_validate(parsed_args)
            elif parsed_args.command == 'query':
                return self.cmd_query(parsed_args)
            elif parsed_args.command == 'status':
                return self.cmd_status(parsed_args)
            elif parsed_args.command == 'health':
                return self.cmd_health(parsed_args)
            else:
                parser.print_help()
                return 1
                
        except KeyboardInterrupt:
            print("\n\nInterrupted by user")
            return 130
        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()
            return 1


def main(args: Optional[List[str]] = None) -> int:
    """Main entry point.
    
    Args:
        args: Command-line arguments
        
    Returns:
        Exit code
    """
    cli = GraphRAGOptimizerCLI()
    return cli.run(args)


if __name__ == '__main__':
    sys.exit(main())
