"""Benchmark safety and reproducibility tests. No Docker needed here."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benchmarks.run_code_eval import DATASET, _sandbox, extract_source, load_tasks
from benchmarks.sandbox_worker import validate_candidate, execute


class BenchmarkFixtureTests(unittest.TestCase):
    def test_version_and_all_reference_solutions_pass_worker(self):
        dataset = load_tasks()
        self.assertEqual(dataset["version"], 1)
        self.assertGreaterEqual(len(dataset["tasks"]), 5)
        ids = set()
        for task in dataset["tasks"]:
            self.assertNotIn(task["id"], ids)
            ids.add(task["id"])
            result = execute(task, task["reference"])
            self.assertEqual(result["passed"], result["total"], (task["id"], result))

    def test_reject_imports_unsafe_calls_reflection_dunder_and_top_level_execution(self):
        samples = [
            "import os\ndef sum_even(numbers): return 2",
            "def sum_even(numbers):\n    return open('/etc/passwd').read()",
            "def sum_even(numbers):\n    return numbers.__class__",
            "def sum_even(numbers):\n    return getattr(numbers, 'secret')",
            "print('side effect')\ndef sum_even(numbers): return 2",
            "def sum_even(numbers):\n    while True: pass",
            "def sum_even(numbers):\n    raise RuntimeError('bad')",
            "def sum_even(numbers):\n    return __import__('os')",
            "def sum_even(numbers):\n    return ().__class__.__base__",
        ]
        for source in samples:
            with self.subTest(source=source):
                with self.assertRaises(ValueError):
                    validate_candidate(source, "sum_even")

    def test_incorrect_results_are_not_mistaken_for_success(self):
        task = load_tasks()["tasks"][0]
        result = execute(task, "def sum_even(numbers):\n    return 0\n")
        self.assertLess(result["passed"], result["total"])
        self.assertEqual(result["total"], len(task["cases"]))

    def test_code_fence_extraction(self):
        code = "def sum_even(numbers):\n    return 0\n"
        self.assertEqual(extract_source("```python\n" + code + "```"), code)
        self.assertEqual(extract_source(code), code)

    def test_docker_flags_and_nonroot_user_are_required(self):
        task = load_tasks()["tasks"][0]
        class Finished:
            returncode = 0
            stdout = '{"passed":1,"total":5,"outcomes":[]}'
            stderr = ""
        with patch("benchmarks.run_code_eval.subprocess.run", return_value=Finished()) as call:
            result = _sandbox(task, task["reference"])
        command = call.call_args.args[0]
        for flag in ("--network=none", "--read-only", "--cap-drop=ALL",
                     "--security-opt=no-new-privileges", "--pids-limit=32",
                     "--memory=128m", "--cpus=0.5", "--user=65534:65534"):
            self.assertIn(flag, command)
        self.assertEqual(result["total"], 5)


if __name__ == "__main__":
    unittest.main()
