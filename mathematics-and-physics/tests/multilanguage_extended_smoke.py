"""Extended independent Docker runtime smoke for five more languages."""
from code_runtime.runner import execute


def main():
    cases = {
        "go": ("package main\nimport \"fmt\"\nfunc main(){ fmt.Println(\"GO=ok\") }", "GO=ok"),
        "rust": ("fn main() { println!(\"RUST=ok\"); }", "RUST=ok"),
        "java": ("public class Main { public static void main(String[] args) "
                 "{ System.out.println(\"JAVA=ok\"); } }", "JAVA=ok"),
        "ruby": ("puts 'RUBY=ok'", "RUBY=ok"),
        "php": ("<?php echo \"PHP=ok\\n\";", "PHP=ok"),
    }
    for language, (code, expected) in cases.items():
        result = execute(language, code, timeout=60)
        assert result["success"], (language, result)
        assert expected in result["stdout"], (language, result)
        print("PASS", language, result["elapsed_seconds"], flush=True)


if __name__ == "__main__":
    main()
