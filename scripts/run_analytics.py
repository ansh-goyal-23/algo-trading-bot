"""
Runs the full analytics pipeline on a completed backtest run.
Executes: trade_analyzer → performance_metrics → report_generator

Usage:
    python -m scripts.run_analytics reports/RUN_XXXXXXXX_XXXXXX/
"""
import sys
from pathlib import Path
from analytics.trade_analyzer    import analyze, print_summary
from analytics.performance_metrics import compute_metrics, print_report, save_reports
from analytics.report_generator  import generate


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m scripts.run_analytics <run_dir>")
        sys.exit(1)

    run_dir  = sys.argv[1]
    run_path = Path(run_dir)

    print(f"\nRunning analytics for {run_path.name}...\n")

    # Step 1 — Trade Analyzer
    print("=" * 50)
    print("STEP 1: Trade Analyzer")
    print("=" * 50)
    trade_analysis = analyze(run_path / "trade_history.csv")
    trade_analysis.to_csv(run_path / "trade_analysis.csv", index=False)
    print_summary(trade_analysis)

    # Step 2 — Performance Metrics
    print("\n" + "=" * 50)
    print("STEP 2: Performance Metrics")
    print("=" * 50)
    metrics = compute_metrics(run_dir)
    print_report(metrics)
    save_reports(metrics, run_dir)

    # Step 3 — Report Generator
    print("\n" + "=" * 50)
    print("STEP 3: Report Generator")
    print("=" * 50)
    report_path = generate(run_dir)
    print(f"Open in browser: open {report_path}")


if __name__ == "__main__":
    main()
