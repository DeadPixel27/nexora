"""Eval package — golden-set extraction accuracy harness."""

from app.services.evals.harness import EvalHarnessResult, run_eval_suite
from app.services.evals.scoring import DocResult, FieldScore

__all__ = [
    "DocResult",
    "EvalHarnessResult",
    "FieldScore",
    "run_eval_suite",
]
