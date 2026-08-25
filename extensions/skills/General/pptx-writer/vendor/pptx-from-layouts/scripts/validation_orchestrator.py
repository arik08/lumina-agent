#!/usr/bin/env python3
"""
Validation Orchestrator for PPTX Generation.

Combines visual validation (render comparison) with content validation
(text, typography, tables) to provide comprehensive quality assessment.

Features:
- Visual diff against template baseline
- Content accuracy validation against reference
- Fix suggestions for flagged issues
- Threshold-based pass/fail determination

Usage:
    from validation_orchestrator import run_comprehensive_validation

    result = run_comprehensive_validation(
        pptx_path="output.pptx",
        template_path="template.pptx",
        layout_plan=layout_plan_dict,
        reference_path="reference.pptx",  # Optional
        threshold=90.0
    )
"""

import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ValidationSummary:
    """Summary of comprehensive validation results."""
    overall_score: float
    passed: bool
    visual_score: float
    content_score: float
    flagged_slides: list = field(default_factory=list)
    fix_suggestions: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    details: dict = field(default_factory=dict)


def run_comprehensive_validation(
    pptx_path: str,
    template_path: str,
    layout_plan: dict,
    reference_path: Optional[str] = None,
    threshold: float = 90.0,
    output_dir: Optional[str] = None
) -> ValidationSummary:
    """
    Run combined visual and content validation.

    Args:
        pptx_path: Path to generated PPTX file
        template_path: Path to template PPTX for visual baseline
        layout_plan: Layout plan dict with slide specifications
        reference_path: Optional path to reference PPTX for content comparison
        threshold: Minimum score to pass (default 90.0)
        output_dir: Optional output directory for composite images

    Returns:
        ValidationSummary with scores, flagged slides, and fix suggestions
    """
    if output_dir is None:
        output_dir = str(Path(pptx_path).parent)

    flagged_slides = []
    fix_suggestions = []
    warnings = []
    visual_score = 100.0
    content_score = 100.0

    # === VISUAL VALIDATION ===
    visual_details = {}
    try:
        from visual_validator import validate_visual

        visual_result = validate_visual(
            pptx_path=pptx_path,
            template_path=template_path,
            layout_plan=layout_plan,
            output_dir=output_dir
        )

        if visual_result.get('error'):
            warnings.append(f"Visual validation failed: {visual_result['error']}")
        else:
            visual_details = visual_result

            # Check per-slide diffs
            for diff in visual_result.get('diffs', []):
                if diff.get('exceeds_threshold'):
                    slide_num = diff['slide']
                    diff_score = diff['score']
                    flagged_slides.append({
                        'slide': slide_num,
                        'issue': 'visual_diff',
                        'severity': 'high' if diff_score > 20 else 'medium',
                        'score': diff_score
                    })

            # Calculate visual score based on average diff
            diffs = visual_result.get('diffs', [])
            if diffs:
                avg_diff = sum(d.get('score', 0) for d in diffs) / len(diffs)
                # Convert diff score to quality score (lower diff = higher quality)
                visual_score = max(0, 100 - avg_diff * 2)

            warnings.extend(visual_result.get('warnings', []))

    except ImportError:
        warnings.append("Visual validator not available (missing dependencies)")
    except Exception as e:
        warnings.append(f"Visual validation error: {str(e)}")

    # === CONTENT VALIDATION (if reference provided) ===
    content_details = {}
    if reference_path and Path(reference_path).exists():
        try:
            # Import from slide-validator skill
            import sys
            validator_path = Path(__file__).parent.parent.parent.parent / 'slide-validator' / 'scripts'
            if str(validator_path) not in sys.path:
                sys.path.insert(0, str(validator_path))

            from validate_pptx import PPTXValidator

            validator = PPTXValidator(
                output_path=pptx_path,
                reference_path=reference_path,
                strict=False
            )
            score, report = validator.validate()

            content_score = score
            content_details = report

            # Extract flagged slides from content validation
            for result in report.get('results', []):
                if not result.get('passed') and result.get('weight', 0) > 5:
                    details = result.get('details', {})
                    slide_num = details.get('slide_number', 0)
                    if slide_num > 0:
                        flagged_slides.append({
                            'slide': slide_num,
                            'issue': result.get('category', 'content'),
                            'severity': 'high' if result['weight'] >= 10 else 'medium',
                            'message': result.get('message', '')
                        })

        except ImportError:
            warnings.append("Content validator not available")
        except Exception as e:
            warnings.append(f"Content validation error: {str(e)}")

    # === GENERATE FIX SUGGESTIONS ===
    fix_suggestions = generate_fix_suggestions(
        flagged_slides=flagged_slides,
        layout_plan=layout_plan,
        visual_details=visual_details,
        content_details=content_details
    )

    # === CALCULATE OVERALL SCORE ===
    # Weight visual and content equally if both available
    if reference_path and Path(reference_path).exists():
        overall_score = (visual_score * 0.4 + content_score * 0.6)
    else:
        overall_score = visual_score

    # Deduplicate flagged slides
    seen = set()
    unique_flagged = []
    for fs in flagged_slides:
        key = (fs['slide'], fs['issue'])
        if key not in seen:
            seen.add(key)
            unique_flagged.append(fs)
    flagged_slides = unique_flagged

    return ValidationSummary(
        overall_score=round(overall_score, 2),
        passed=overall_score >= threshold,
        visual_score=round(visual_score, 2),
        content_score=round(content_score, 2),
        flagged_slides=flagged_slides,
        fix_suggestions=fix_suggestions,
        warnings=warnings,
        details={
            'visual': visual_details,
            'content': content_details,
            'threshold': threshold
        }
    )


def generate_fix_suggestions(
    flagged_slides: list,
    layout_plan: dict,
    visual_details: dict,
    content_details: dict
) -> list:
    """
    Analyze validation failures and generate actionable fix suggestions.

    Returns list of suggestion dicts with:
    - slide: slide number
    - issue: issue type
    - suggestion: actionable fix text
    - priority: 'high', 'medium', 'low'
    """
    suggestions = []
    slides_data = layout_plan.get('slides', [])

    for flagged in flagged_slides:
        slide_num = flagged.get('slide', 0)
        issue = flagged.get('issue', '')
        severity = flagged.get('severity', 'medium')

        # Get slide info from layout plan
        slide_info = None
        if 0 < slide_num <= len(slides_data):
            slide_info = slides_data[slide_num - 1]

        suggestion = None

        if issue == 'visual_diff':
            # High visual diff - could be layout mismatch or content issue
            if slide_info:
                layout_name = slide_info.get('layout', {}).get('name', '')
                visual_type = slide_info.get('visual_type', '')
                suggestion = {
                    'slide': slide_num,
                    'issue': 'visual_layout',
                    'suggestion': f"Slide {slide_num}: Verify layout '{layout_name}' matches expected positioning. Visual type: '{visual_type}'. Check for overflow or misplaced content.",
                    'priority': 'high' if severity == 'high' else 'medium'
                }
            else:
                suggestion = {
                    'slide': slide_num,
                    'issue': 'visual_layout',
                    'suggestion': f"Slide {slide_num}: Check layout positioning and content overflow.",
                    'priority': 'medium'
                }

        elif issue == 'title_match':
            suggestion = {
                'slide': slide_num,
                'issue': 'title_mismatch',
                'suggestion': f"Slide {slide_num}: Title text doesn't match reference. Check for typos or formatting issues.",
                'priority': 'high'
            }

        elif issue == 'body_match':
            suggestion = {
                'slide': slide_num,
                'issue': 'content_mismatch',
                'suggestion': f"Slide {slide_num}: Body content differs from reference. Review bullet points and paragraph text.",
                'priority': 'high'
            }

        elif issue == 'typography':
            suggestion = {
                'slide': slide_num,
                'issue': 'typography',
                'suggestion': f"Slide {slide_num}: Typography mismatch detected. Check font styling (bold, italic, color markers like {{blue}}, {{signpost}}).",
                'priority': 'medium'
            }

        elif issue == 'text_overflow':
            suggestion = {
                'slide': slide_num,
                'issue': 'overflow',
                'suggestion': f"Slide {slide_num}: Text exceeds placeholder bounds. Consider reducing content or splitting across slides.",
                'priority': 'high'
            }

        elif issue == 'table_structure':
            suggestion = {
                'slide': slide_num,
                'issue': 'table_structure',
                'suggestion': f"Slide {slide_num}: Table structure (rows/columns) doesn't match. Verify table data format.",
                'priority': 'medium'
            }

        elif issue == 'layout_match':
            if slide_info:
                layout_name = slide_info.get('layout', {}).get('name', '')
                suggestion = {
                    'slide': slide_num,
                    'issue': 'wrong_layout',
                    'suggestion': f"Slide {slide_num}: Using layout '{layout_name}' but reference uses different layout. Check layout assignment in slide-outline-to-layout.",
                    'priority': 'high'
                }

        if suggestion:
            suggestions.append(suggestion)

    # Sort by priority and slide number
    priority_order = {'high': 0, 'medium': 1, 'low': 2}
    suggestions.sort(key=lambda s: (priority_order.get(s['priority'], 2), s['slide']))

    return suggestions


def format_validation_report(summary: ValidationSummary) -> str:
    """Format validation summary as human-readable report."""
    lines = []
    lines.append("=" * 60)
    lines.append("VALIDATION REPORT")
    lines.append("=" * 60)
    lines.append("")
    lines.append(f"Overall Score: {summary.overall_score:.1f}% {'PASSED' if summary.passed else 'FAILED'}")
    lines.append(f"  Visual Score: {summary.visual_score:.1f}%")
    lines.append(f"  Content Score: {summary.content_score:.1f}%")
    lines.append("")

    if summary.flagged_slides:
        lines.append("-" * 40)
        lines.append(f"FLAGGED SLIDES ({len(summary.flagged_slides)}):")
        lines.append("-" * 40)
        for fs in summary.flagged_slides:
            lines.append(f"  Slide {fs['slide']}: {fs['issue']} [{fs['severity']}]")
        lines.append("")

    if summary.fix_suggestions:
        lines.append("-" * 40)
        lines.append(f"FIX SUGGESTIONS ({len(summary.fix_suggestions)}):")
        lines.append("-" * 40)
        for sug in summary.fix_suggestions:
            lines.append(f"  [{sug['priority'].upper()}] {sug['suggestion']}")
        lines.append("")

    if summary.warnings:
        lines.append("-" * 40)
        lines.append("WARNINGS:")
        lines.append("-" * 40)
        for w in summary.warnings:
            lines.append(f"  - {w}")
        lines.append("")

    lines.append("=" * 60)

    return "\n".join(lines)


# CLI interface
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Comprehensive PPTX validation")
    parser.add_argument("pptx_path", help="Path to generated PPTX")
    parser.add_argument("template_path", help="Path to template PPTX")
    parser.add_argument("layout_plan", help="Path to layout plan JSON")
    parser.add_argument("--reference", help="Path to reference PPTX for content validation")
    parser.add_argument("--threshold", type=float, default=90.0, help="Pass threshold (default: 90)")
    parser.add_argument("--output-dir", help="Output directory for composite images")
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    # Load layout plan
    with open(args.layout_plan) as f:
        layout_plan = json.load(f)

    # Run validation
    summary = run_comprehensive_validation(
        pptx_path=args.pptx_path,
        template_path=args.template_path,
        layout_plan=layout_plan,
        reference_path=args.reference,
        threshold=args.threshold,
        output_dir=args.output_dir
    )

    if args.json:
        import dataclasses
        print(json.dumps(dataclasses.asdict(summary), indent=2))
    else:
        print(format_validation_report(summary))

    # Exit with appropriate code
    exit(0 if summary.passed else 1)
