"""Operator-only multi-language execution safety checks."""
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from code_runtime import cli, runner


class RuntimeRegistryTests(unittest.TestCase):
    def test_language_registry_and_extension_mapping(self):
        self.assertEqual(set(runner.RUNTIMES), {
            "python", "javascript", "c", "cpp", "go", "rust",
            "java", "ruby", "php"})
        self.assertEqual(runner.language_for(Path("Main.java")), "java")
        self.assertEqual(runner.language_for(Path("source.cc")), "cpp")
        self.assertEqual(runner.language_for(Path("main.py")), "python")
        with self.assertRaises(ValueError):
            runner.language_for(Path("script.sh"))

    def test_reject_unknown_lang_large_code_and_long_input(self):
        with self.assertRaises(ValueError):
            runner.execute("bash", "echo hello")
        with self.assertRaises(ValueError):
            runner.execute("python", "x" * (runner.MAX_CODE_BYTES + 1))
        with self.assertRaises(ValueError):
            runner.execute("python", "print(1)", stdin="x" * (runner.MAX_INPUT_BYTES + 1))
        for invalid in (0, 61, -1, True):
            with self.subTest(timeout=invalid), self.assertRaises(ValueError):
                runner.execute("python", "print(1)", timeout=invalid)

    def test_execution_command_never_interpolates_source_or_user_stdin(self):
        observed = {}
        def fake_bounded(command, *, container_name, timeout):
            observed["command"] = command
            observed["name"] = container_name
            return {"exit_code": 0, "stdout": "ok", "stderr": "",
                    "timed_out": False, "output_limited": False,
                    "elapsed_seconds": 0.01}

        with patch("code_runtime.runner._bounded_output", side_effect=fake_bounded):
            output = runner.execute("python", "print('secret source')",
                                    stdin="PRIVATE INPUT")
        self.assertTrue(output["success"])
        command = observed["command"]
        command_text = " ".join(command)
        self.assertNotIn("secret source", command_text)
        self.assertNotIn("PRIVATE INPUT", command_text)
        for flag in ("--pull=never", "--network=none", "--read-only",
                     "--cap-drop=ALL", "--security-opt=no-new-privileges",
                     "--ipc=none", "--pids-limit=64", "--memory=512m",
                     "--memory-swap=512m", "--cpus=2", "--user=65534:65534"):
            self.assertIn(flag, command)
        self.assertTrue(observed["name"].startswith("lab-code-"))

    def test_local_model_requires_trusted_checkpoint_and_explicit_file(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "main.py"
            path.write_text("print('safe')", encoding="utf-8")
            with patch("code_runtime.cli.execute", return_value={"success": True}) as run:
                result = cli.run_file(path)
                self.assertEqual(result["success"], True)
                run.assert_called_once_with("python", "print('safe')", "", timeout=60)
            with self.assertRaises(ValueError):
                cli.run_model(path.with_suffix(".pt"), "Create a function", "python")

    def test_fenced_model_code_and_retry_limit(self):
        self.assertEqual(cli.extract_code("```python\nprint(42)\n```"), "print(42)\n")
        with tempfile.TemporaryDirectory() as tmp:
            model = Path(tmp) / "trusted.pt"
            model.write_bytes(b"operator-local-checkpoint")
            with patch("code_runtime.cli.generate_from_checkpoint",
                       return_value="print(1)\n") as generate, \
                 patch("code_runtime.cli.execute", side_effect=[
                     {"success": False, "stderr": "syntax error", "stdout": ""},
                     {"success": True, "stderr": "", "stdout": "1\n"},
                 ]) as execute:
                report = cli.run_model(model, "Write Python", "python", fix_attempts=1)
            self.assertEqual(len(report["attempts"]), 2)
            self.assertEqual(generate.call_count, 2)
            self.assertEqual(execute.call_count, 2)
            with self.assertRaises(ValueError):
                cli.run_model(model, "Write Python", "python", fix_attempts=3)


if __name__ == "__main__":
    unittest.main()
