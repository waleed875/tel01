"""Only runs inside the Docker sandbox; NEVER execute candidate code on host.

AST checks are defense in depth. They are not a general Python sandbox.
This process deliberately receives only read-only candidate and case files.
"""
import ast
import json
import sys
from pathlib import Path

ALLOWED_BUILTINS = {
    "abs", "all", "any", "bool", "dict", "enumerate", "float", "int",
    "len", "list", "max", "min", "range", "reversed", "set", "sorted",
    "str", "sum", "tuple", "zip",
}
BANNED_NODES = (
    ast.Import, ast.ImportFrom, ast.Attribute, ast.ClassDef, ast.Lambda,
    ast.With, ast.AsyncWith, ast.Try, ast.Raise, ast.Global, ast.Nonlocal,
    ast.AsyncFunctionDef, ast.Await, ast.Yield, ast.YieldFrom, ast.Delete,
    ast.NamedExpr, ast.While, ast.Match,
)


def validate_candidate(source: str, function: str) -> ast.Module:
    if len(source.encode("utf-8")) > 16_384:
        raise ValueError("Candidate code exceeds 16 KiB")
    try:
        tree = ast.parse(source, mode="exec")
    except SyntaxError as exc:
        raise ValueError("Candidate Python syntax error") from exc
    if not tree.body or not all(isinstance(node, ast.FunctionDef) for node in tree.body):
        raise ValueError("Only function definitions are permitted")
    defined = [node.name for node in tree.body]
    if len(set(defined)) != len(defined) or function not in defined:
        raise ValueError("Required function not defined or duplicate names")
    if len(defined) > 6:
        raise ValueError("Too many function definitions")
    for node in ast.walk(tree):
        if isinstance(node, BANNED_NODES):
            raise ValueError(f"Forbidden Python construct: {type(node).__name__}")
        if isinstance(node, ast.Name) and (
                node.id.startswith("_") or "__" in node.id):
            raise ValueError("Private and dunder identifiers are disallowed")
        if isinstance(node, ast.FunctionDef):
            if node.decorator_list or node.name.startswith("_") or node.returns:
                raise ValueError("Decorators, private functions, annotations not permitted")
            if node.args.kwarg or node.args.vararg or node.args.defaults or node.args.kw_defaults:
                raise ValueError("Only fixed positional arguments are permitted")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or (
                    node.func.id not in ALLOWED_BUILTINS and node.func.id not in defined):
                raise ValueError("Only allowlisted built-ins or defined functions may be called")
        if isinstance(node, ast.Constant) and isinstance(node.value, (bytes, complex)):
            raise ValueError("Unsupported constant type")
    return tree


def execute(task: dict, source: str) -> dict:
    function = task["function"]
    try:
        tree = validate_candidate(source, function)
    except ValueError as exc:
        return {"error": str(exc), "passed": 0, "total": len(task["cases"]), "outcomes": []}
    allowed = {key: getattr(__builtins__, key) for key in ALLOWED_BUILTINS}
    namespace = {"__builtins__": allowed}
    try:
        exec(compile(tree, "<candidate>", "exec"), namespace, namespace)
        fn = namespace[function]
        outcomes = []
        for case in task["cases"]:
            try:
                actual = fn(*case["args"])
                correct = type(actual) is type(case["expected"]) and actual == case["expected"]
                # Do not print untrusted candidate result strings.
                outcomes.append({"passed": bool(correct)})
            except BaseException:
                outcomes.append({"passed": False})
        return {"passed": sum(x["passed"] for x in outcomes),
                "total": len(outcomes), "outcomes": outcomes}
    except BaseException:
        return {"error": "Candidate execution failed", "passed": 0,
                "total": len(task["cases"]), "outcomes": []}


def main():
    folder = Path("/work")
    task = json.loads((folder / "task.json").read_text(encoding="utf-8"))
    source = (folder / "candidate.py").read_text(encoding="utf-8")
    print(json.dumps(execute(task, source), sort_keys=True))


if __name__ == "__main__":
    main()
