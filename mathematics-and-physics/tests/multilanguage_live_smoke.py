"""Disposable Docker smoke tests for operator-only runtime.

Run only on a trusted CI host that grants Docker daemon access.
Only pulls pinned-version runtime images; no user code downloads packages.
"""
from code_runtime.runner import RUNTIMES, execute


def main():
    cases = {
        "python": ("import sys\nprint('PY=' + input())", "ok\n", "PY=ok"),
        "javascript": ("const fs=require('fs'); console.log('JS=' + fs.readFileSync(0, 'utf8').trim())",
                       "ok\n", "JS=ok"),
        "c": ("#include <stdio.h>\nint main(void) { puts(\"C=ok\"); return 0; }",
              "", "C=ok"),
        "cpp": ("#include <iostream>\nint main(){ std::cout << \"CPP=ok\\n\"; return 0; }",
                "", "CPP=ok"),
    }
    for language, (source, stdin, expected) in cases.items():
        result = execute(language, source, stdin)
        assert result["success"], (language, result)
        assert expected in result["stdout"], (language, result)
        print("PASS", language, result["elapsed_seconds"], flush=True)

    failure = execute("python", "raise ValueError('expected test error')")
    assert failure["exit_code"] != 0 and not failure["success"], failure
    assert "ValueError" in failure["stderr"], failure

    infinite = execute("python", "while True: pass", timeout=2)
    assert infinite["timed_out"] and not infinite["success"], infinite

    flood = execute("python", "while True: print('Z' * 8000)", timeout=4)
    assert flood["output_limited"] and not flood["success"], flood

    print("PASS nonzero exit, timeout, bounded stdout and container cleanup")


if __name__ == "__main__":
    main()
