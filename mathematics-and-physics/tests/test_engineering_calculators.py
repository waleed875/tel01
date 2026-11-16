"""Independent functional checks for deterministic engineering tools and API."""
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from engineering_calculators import calculate, get_catalog
from webapp import app, session_user


class EngineeringCalculatorTests(unittest.TestCase):
    def test_math_polynomial_and_derivative(self):
        out = calculate("math.polynomial", {"coefficients": [3, 2, 1], "x": 2})
        self.assertAlmostEqual(out["values"]["value"], 17)
        self.assertAlmostEqual(out["values"]["derivative_at_x"], 14)
        self.assertEqual(out["values"]["derivative_coefficients"], [6, 2])
        constant = calculate("math.polynomial", {"coefficients": [5], "x": -9})
        self.assertEqual(constant["values"]["derivative_at_x"], 0)

    def test_quadratic_real_repeated_complex_and_linear_rejection(self):
        real = calculate("math.quadratic", {"a": 1, "b": -3, "c": 2})
        self.assertEqual(real["values"]["real_roots"], [1, 2])
        self.assertEqual(calculate("math.quadratic", {"a": 1, "b": -2, "c": 1})
                         ["values"]["real_roots"], [1, 1])
        complex_values = calculate("math.quadratic", {"a": 1, "b": 0, "c": 1})
        self.assertEqual(complex_values["values"]["real_roots"], [])
        self.assertEqual({r["imaginary"] for r in complex_values["values"]["complex_roots"]},
                         {-1, 1})
        with self.assertRaises(ValueError):
            calculate("math.quadratic", {"a": 0, "b": 2, "c": 1})

    def test_electronics_ohm_and_series_parallel(self):
        out = calculate("electronics.ohm", {"voltage": 12, "resistance": 1000})
        self.assertAlmostEqual(out["values"]["current_a"], .012)
        self.assertAlmostEqual(out["values"]["power_w"], .144)
        series = calculate("electronics.resistors",
                           {"resistances": [100, 200], "connection": "series"})
        self.assertAlmostEqual(series["values"]["equivalent_ohms"], 300)
        parallel = calculate("electronics.resistors",
                             {"resistances": [100, 100], "connection": "parallel"})
        self.assertAlmostEqual(parallel["values"]["equivalent_ohms"], 50)
        with self.assertRaises(ValueError):
            calculate("electronics.resistors",
                      {"resistances": [0, 100], "connection": "parallel"})

    def test_physics_valid_values_and_units(self):
        force = calculate("physics.force", {"mass": 3, "acceleration": -4})
        self.assertEqual(force["values"]["force_n"], -12)
        self.assertIn("F = ma", force["formula"])
        energy = calculate("physics.kinetic_energy", {"mass": 2, "velocity": -3})
        self.assertEqual(energy["values"]["energy_j"], 9)
        speed = calculate("physics.velocity", {"distance": 150, "time": 30})
        self.assertEqual(speed["values"]["speed_m_s"], 5)

    def test_bad_type_extra_args_and_numeric_limits(self):
        for operation, payload in [
            ("physics.force", {"mass": True, "acceleration": 1}),
            ("physics.force", {"mass": -2, "acceleration": 1}),
            ("physics.force", {"mass": 2, "acceleration": float("inf")}),
            ("electronics.ohm", {"voltage": 12, "resistance": 0}),
            ("physics.velocity", {"distance": 100, "time": 0}),
            ("math.polynomial", {"coefficients": [], "x": 2}),
            ("physics.force", {"mass": 1, "acceleration": 2, "extra": 5}),
            ("physics.force", {"mass": 1}),
            ("math.quadratic", {"a": 1, "b": 2, "c": 1e100}),
            ("math.polynomial", {"coefficients": [1, 1], "x": 1e13}),
            ("unsupported.eval", {}),
        ]:
            with self.subTest(operation=operation, payload=payload):
                with self.assertRaises(ValueError):
                    calculate(operation, payload)

    def test_python_ast_does_not_execute_code(self):
        dangerous = "import os\nos.system('touch /tmp/must_not_exist')\n"
        with patch("os.system", side_effect=AssertionError("Code ran!")):
            out = calculate("software.analyze_python", {"source": dangerous})
        self.assertTrue(out["values"]["valid_syntax"])
        self.assertEqual(out["values"]["imports"], 1)
        self.assertFalse(calculate("software.analyze_python",
                                  {"source": "def bad(: pass"})["values"]["valid_syntax"])
        for src in ("", "x" * 16001):
            with self.assertRaises(ValueError):
                calculate("software.analyze_python", {"source": src})

    def test_all_operations_are_in_scope(self):
        catalog = get_catalog()
        self.assertTrue(catalog["read_only"])
        self.assertEqual(set(item["domain"] for item in catalog["operations"].values()),
                         {"math", "electronics", "physics", "software"})


class EngineeringAPITests(unittest.TestCase):
    def setUp(self):
        app.dependency_overrides[session_user] = lambda: 101
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_authenticated_discovery_and_calculation(self):
        discovery = self.client.get("/api/engineering/tools")
        self.assertEqual(discovery.status_code, 200)
        self.assertEqual(len(discovery.json()["operations"]), 8)
        calc = self.client.post("/api/engineering/calculate", json={
            "operation": "physics.force", "inputs": {"mass": 3, "acceleration": 4}})
        self.assertEqual(calc.status_code, 200, calc.text)
        self.assertEqual(calc.json()["values"]["force_n"], 12)

    def test_invalid_operation_rejected_without_model_or_gitea_access(self):
        with patch("webapp.model", None), patch("webapp.GiteaClient") as git:
            r = self.client.post("/api/engineering/calculate", json={
                "operation": "physics.force", "inputs": {"mass": -3, "acceleration": 4}})
            self.assertEqual(r.status_code, 422)
            git.assert_not_called()


if __name__ == "__main__":
    unittest.main()
