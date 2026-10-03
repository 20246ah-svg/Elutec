"""Safe, shared evaluator for user-defined analysis formulas.

User formulas are useful for exploratory SARA analysis, but they must never get
access to Python internals, files, processes, or the network.  This module
validates a small numerical expression language before evaluating it against a
caller-supplied data environment.
"""

from __future__ import annotations

import ast
from typing import Any, Mapping, Optional, Set

import numpy as np


class FormulaValidationError(ValueError):
    """Raised when a formula is outside the supported numerical language."""


# Keep this explicit.  In particular, do not accept arbitrary ``np.*``
# attributes: several NumPy internals expose Python objects that should not be
# reachable from a persisted user setting.
NUMPY_FUNCTIONS = frozenset({
    "abs", "clip", "cos", "exp", "gradient", "log", "log10", "maximum",
    "mean", "median", "minimum", "nanmean", "nanmedian", "nanstd", "sin",
    "sqrt", "std", "sum", "where",
})
NUMPY_CONSTANTS = frozenset({"e", "pi"})
SAFE_FUNCTIONS = {
    "abs": np.abs,
    "min": min,
    "max": max,
    "round": round,
    "float": float,
    "int": int,
    "log10": np.log10,
    "sqrt": np.sqrt,
    "exp": np.exp,
    "sin": np.sin,
    "cos": np.cos,
    "mean": np.mean,
}

_ALLOWED_NODE_TYPES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.BoolOp,
    ast.Compare,
    ast.Call,
    ast.Name,
    ast.Load,
    ast.Constant,
    ast.Attribute,
    ast.Tuple,
    ast.List,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.USub,
    ast.UAdd,
    ast.And,
    ast.Or,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
)


def _callable_name(node: ast.AST) -> Optional[str]:
    """Return an approved function spelling, otherwise ``None``."""
    if isinstance(node, ast.Name) and node.id in SAFE_FUNCTIONS:
        return node.id
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "np"
        and node.attr in NUMPY_FUNCTIONS
    ):
        return f"np.{node.attr}"
    return None


def validate_formula(formula: str, allowed_names: Optional[Set[str]] = None) -> ast.Expression:
    """Parse and validate a numerical formula.

    ``allowed_names`` is optional to support validating a formula while a user
    is creating custom variables.  At evaluation time it should contain the
    complete data environment, which also catches spelling mistakes early.
    """
    if not isinstance(formula, str) or not formula.strip():
        raise FormulaValidationError("Формула пуста.")
    if len(formula) > 1000:
        raise FormulaValidationError("Формула длиннее допустимых 1000 символов.")

    try:
        tree = ast.parse(formula, mode="eval")
    except SyntaxError as exc:
        raise FormulaValidationError(f"Синтаксическая ошибка формулы: {exc.msg}") from exc

    permitted_names = set(allowed_names or ()) | set(SAFE_FUNCTIONS) | {"np"}
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODE_TYPES):
            raise FormulaValidationError(
                f"Недопустимая конструкция в формуле: {type(node).__name__}."
            )
        if isinstance(node, ast.Name):
            if node.id.startswith("_"):
                raise FormulaValidationError("Имена, начинающиеся с '_', запрещены.")
            if allowed_names is not None and node.id not in permitted_names:
                raise FormulaValidationError(f"Неизвестная переменная или функция: {node.id}")
        elif isinstance(node, ast.Attribute):
            if not (
                isinstance(node.value, ast.Name)
                and node.value.id == "np"
                and node.attr in NUMPY_FUNCTIONS | NUMPY_CONSTANTS
            ):
                raise FormulaValidationError("Разрешены только перечисленные функции NumPy (np.*).")
        elif isinstance(node, ast.Call) and _callable_name(node.func) is None:
            raise FormulaValidationError("Вызов этой функции в формулах не разрешён.")

    return tree


def evaluate_formula(formula: str, environment: Mapping[str, Any]) -> Any:
    """Evaluate a previously validated numeric formula without Python builtins."""
    tree = validate_formula(formula, set(environment))
    local_environment = dict(SAFE_FUNCTIONS)
    local_environment.update(environment)
    local_environment["np"] = np
    return eval(compile(tree, "<elutek-formula>", "eval"), {"__builtins__": {}}, local_environment)


def is_safe_variable_name(name: str, reserved_names: Optional[Set[str]] = None) -> bool:
    """Return whether a custom-variable name can safely enter an environment."""
    if not isinstance(name, str) or not name.isidentifier() or name.startswith("_"):
        return False
    reserved = set(SAFE_FUNCTIONS) | {"np"}
    if reserved_names:
        reserved.update(reserved_names)
    return name not in reserved
