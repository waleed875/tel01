"""Deterministic, bounded engineering calculations for the four project domains.

No AI model is involved in these results. No eval, exec, sympify, network,
file access, arbitrary units or user-supplied program execution.
"""
import ast
import math
from collections import Counter

MAX_SOURCE_CHARS = 16000
MAX_COEFFICIENTS = 21
MAX_MAGNITUDE = 1e12

OPERATIONS = {
    "math.polynomial": {
        "label": "تقييم كثيرة حدود ومشتقتها",
        "domain": "math",
        "inputs": ["coefficients", "x"],
        "description": "المعاملات مرتبة من أعلى درجة إلى الثابت؛ احسب قيمة f(x) والمشتقة f'(x).",
    },
    "math.quadratic": {
        "label": "حل معادلة تربيعية حقيقية",
        "domain": "math",
        "inputs": ["a", "b", "c"],
        "description": "حل ax² + bx + c = 0، مع بيان الجذور الحقيقية أو المركبة.",
    },
    "electronics.ohm": {
        "label": "قانون أوم",
        "domain": "electronics",
        "inputs": ["voltage", "resistance"],
        "description": "احسب التيار والقدرة من جهد ومقاومة موجبة لدائرة مقاومة مثالية.",
    },
    "electronics.resistors": {
        "label": "مقاومات على التوالي أو التوازي",
        "domain": "electronics",
        "inputs": ["resistances", "connection"],
        "description": "احسب المقاومة المكافئة لمقاومات موجبة.",
    },
    "physics.force": {
        "label": "قانون نيوتن الثاني",
        "domain": "physics",
        "inputs": ["mass", "acceleration"],
        "description": "احسب محصلة القوة F = ma بوحدة نيوتن.",
    },
    "physics.kinetic_energy": {
        "label": "الطاقة الحركية",
        "domain": "physics",
        "inputs": ["mass", "velocity"],
        "description": "احسب Ek = ½mv² بوحدة جول.",
    },
    "physics.velocity": {
        "label": "السرعة المتوسطة",
        "domain": "physics",
        "inputs": ["distance", "time"],
        "description": "احسب متوسط السرعة من المسافة والزمن الموجبين.",
    },
    "software.analyze_python": {
        "label": "تحليل بنية Python دون تنفيذ",
        "domain": "software",
        "inputs": ["source"],
        "description": "تحقق من صحة الصياغة واستخرج عدد الدوال والأصناف والاستيرادات.",
    },
}


def _number(value, name: str, *, nonnegative=False, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a JSON number")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{name} outside numeric range") from exc
    if not math.isfinite(result) or abs(result) > MAX_MAGNITUDE:
        raise ValueError(f"{name} must be finite and within ±1e12")
    if positive and result <= 0:
        raise ValueError(f"{name} must be positive")
    if nonnegative and result < 0:
        raise ValueError(f"{name} must be nonnegative")
    return result


def _list_numbers(value, name, *, positive=False, maximum=20):
    if not isinstance(value, list) or not 1 <= len(value) <= maximum:
        raise ValueError(f"{name} requires 1..{maximum} numbers")
    return [_number(item, f"{name}[{i}]", positive=positive)
            for i, item in enumerate(value)]


def _result(operation, fields, *, formula, assumptions):
    for item in fields.values():
        if isinstance(item, (int, float)) and not math.isfinite(item):
            raise ValueError("Calculation overflow")
    return {
        "operation": operation, "domain": OPERATIONS[operation]["domain"],
        "verified_method": "deterministic-formula-or-structural-parser",
        "values": fields, "formula": formula, "assumptions": assumptions,
        "notice": "هذه نتيجة حسابية أو تحليل بنيوي، وليست إجابة صادرة عن النموذج العصبي.",
    }


def calculate(operation: str, data: dict) -> dict:
    if operation not in OPERATIONS:
        raise ValueError("Unsupported engineering operation")
    if not isinstance(data, dict):
        raise ValueError("Inputs must be a JSON object")
    allowed = set(OPERATIONS[operation]["inputs"])
    if set(data) != allowed:
        raise ValueError("Provide exactly the documented operation inputs")
    if operation == "math.polynomial":
        coeff = _list_numbers(data["coefficients"], "coefficients",
                              maximum=MAX_COEFFICIENTS)
        x = _number(data["x"], "x")
        derivative = [coefficient * (len(coeff) - index - 1)
                      for index, coefficient in enumerate(coeff[:-1])]
        value = 0.0
        for coefficient in coeff:
            value = value * x + coefficient
            if not math.isfinite(value) or abs(value) > MAX_MAGNITUDE * 1e6:
                raise ValueError("Polynomial evaluation exceeded safe range")
        slope = 0.0
        for coefficient in derivative:
            slope = slope * x + coefficient
            if not math.isfinite(slope) or abs(slope) > MAX_MAGNITUDE * 1e6:
                raise ValueError("Derivative evaluation exceeded safe range")
        return _result(operation, {
            "value": value, "derivative_at_x": slope,
            "derivative_coefficients": derivative or [0.0],
        }, formula="Horner; derivative coefficients n*a_n",
            assumptions=["Real polynomial coefficients, coefficients in descending degree."])
    if operation == "math.quadratic":
        a, b, c = (_number(data[k], k) for k in ("a", "b", "c"))
        if a == 0:
            raise ValueError("Coefficient a must be nonzero for a quadratic")
        d = b * b - 4 * a * c
        if not math.isfinite(d):
            raise ValueError("Discriminant overflow")
        if d >= 0:
            root = math.sqrt(d)
            # Stable quadratic formula avoids catastrophic cancellation.
            q = -0.5 * (b + math.copysign(root, b)) if b else -0.5 * root
            roots = sorted([q / a, c / q]) if q else [0.0, 0.0]
            result = {"discriminant": d, "real_roots": roots, "complex_roots": []}
        else:
            real, imag = -b / (2 * a), abs(math.sqrt(-d) / (2 * a))
            result = {"discriminant": d, "real_roots": [],
                      "complex_roots": [{"real": real, "imaginary": imag},
                                        {"real": real, "imaginary": -imag}]}
        return _result(operation, result, formula="(-b ± √(b²−4ac))/(2a)",
                       assumptions=["Real coefficients; a must not equal zero."])
    if operation == "electronics.ohm":
        voltage = _number(data["voltage"], "voltage")
        resistance = _number(data["resistance"], "resistance", positive=True)
        current = voltage / resistance
        return _result(operation, {"current_a": current,
                       "power_w": voltage * current},
                       formula="I = V/R; P = V²/R",
                       assumptions=["Ideal linear resistor; SI units V, Ω, A, W."])
    if operation == "electronics.resistors":
        resistors = _list_numbers(data["resistances"], "resistances", positive=True)
        if data["connection"] not in ("series", "parallel"):
            raise ValueError("connection must be series or parallel")
        eq = (math.fsum(resistors) if data["connection"] == "series"
              else 1.0 / math.fsum(1.0 / r for r in resistors))
        return _result(operation, {"equivalent_ohms": eq},
                       formula="Req = ΣR" if data["connection"] == "series" else "1/Req = Σ(1/R)",
                       assumptions=["Ideal resistors; no parasitic wiring resistance."])
    if operation == "physics.force":
        m = _number(data["mass"], "mass", nonnegative=True)
        a = _number(data["acceleration"], "acceleration")
        return _result(operation, {"force_n": m * a},
                       formula="F = ma", assumptions=["Mass in kg; acceleration in m/s²; inertial frame."])
    if operation == "physics.kinetic_energy":
        m = _number(data["mass"], "mass", nonnegative=True)
        v = _number(data["velocity"], "velocity")
        return _result(operation, {"energy_j": 0.5 * m * v * v},
                       formula="Ek = ½mv²", assumptions=["Classical mechanics; kg and m/s."])
    if operation == "physics.velocity":
        distance = _number(data["distance"], "distance", nonnegative=True)
        time_s = _number(data["time"], "time", positive=True)
        return _result(operation, {"speed_m_s": distance / time_s},
                       formula="speed = distance/time",
                       assumptions=["Distance in m and elapsed time in s; nonnegative scalar speed."])
    if operation == "software.analyze_python":
        source = data["source"]
        if not isinstance(source, str) or not 1 <= len(source) <= MAX_SOURCE_CHARS:
            raise ValueError("Python source must contain 1..16000 characters")
        try:
            tree = ast.parse(source)
        except (SyntaxError, ValueError, RecursionError) as exc:
            return _result(operation, {"valid_syntax": False, "error": "Python syntax error"},
                           formula="Python ast.parse()",
                           assumptions=["Syntax checked only; code is not executed."])
        counts = Counter(type(n).__name__ for n in ast.walk(tree))
        return _result(operation, {"valid_syntax": True,
                       "functions": counts["FunctionDef"] + counts["AsyncFunctionDef"],
                       "classes": counts["ClassDef"], "imports": counts["Import"] + counts["ImportFrom"],
                       "loops": counts["For"] + counts["AsyncFor"] + counts["While"],
                       "conditionals": counts["If"]},
                       formula="Python AST node counts",
                       assumptions=["Static syntax structure only; no execution or security/correctness guarantee."])
    raise AssertionError("Missing operation handler")


def get_catalog() -> dict:
    return {"operations": OPERATIONS, "read_only": True,
            "note": "كل الأدوات حسابية أو بنيوية محلية؛ لا تحفظ ملفات ولا تشغّل كودًا."}
