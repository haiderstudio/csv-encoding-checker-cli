#!/usr/bin/env python3
"""Tests for csv_encoding_checker — stdlib unittest only.

Every CSV document in this file is made up for testing.
The bad bytes here are byte fixtures, not secrets — no
real secret appears anywhere in this file.
"""

import ast
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import csv_encoding_checker as checker

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src/csv_encoding_checker.py"


def run_cli(argv):
    """Run main(argv), capture stdout/stderr, return (code, out, err)."""
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            code = checker.main(argv)
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


def write(tmp, name, data):
    path = Path(tmp) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        path.write_bytes(data)
    else:
        path.write_text(data, encoding="utf-8")
    return str(path)


class TestDecodeDetection(unittest.TestCase):
    def test_clean_ascii_passes(self):
        self.assertIsNone(
            checker.check_bytes(b"name,city\nAna,Oslo\n"))

    def test_clean_multibyte_passes(self):
        self.assertIsNone(
            checker.check_bytes(
                "José,Müller,Anaïs\n".encode("utf-8")))

    def test_empty_file_passes(self):
        self.assertIsNone(checker.check_bytes(b""))

    def test_bom_only_passes(self):
        self.assertIsNone(checker.check_bytes(b"\xef\xbb\xbf"))

    def test_bom_then_clean_passes(self):
        self.assertIsNone(
            checker.check_bytes(
                b"\xef\xbb\xbfname\nPriya,Multan\n"))

    def test_bad_byte_on_line_1(self):
        bad = checker.check_bytes(b"\xffname,city\nAna,Oslo\n")
        self.assertEqual(bad["line"], 1)
        self.assertIn("offset 0", bad["reason"])

    def test_bad_byte_on_line_3(self):
        bad = checker.check_bytes(
            b"name,city,notes\nAna,Oslo,paid\n"
            b"Bj\xf8rn,Bergen,overdue\nSara,Leeds,paid\n")
        self.assertEqual(bad["line"], 3)
        self.assertIn("offset 32", bad["reason"])

    def test_first_bad_byte_reported_when_several(self):
        bad = checker.check_bytes(b"a\xffb\nc\xfed\n")
        self.assertEqual(bad["line"], 1)
        self.assertIn("offset 1", bad["reason"])

    def test_lone_continuation_byte_fails(self):
        bad = checker.check_bytes(b"name\n\x80\n")
        self.assertEqual(bad["line"], 2)

    def test_truncated_multibyte_at_end_fails(self):
        bad = checker.check_bytes(b"name,city\nAna,Oslo\xc3")
        self.assertEqual(bad["line"], 2)
        self.assertIn("offset 18", bad["reason"])

    def test_bad_byte_after_valid_multibyte(self):
        bad = checker.check_bytes(
            "José\n".encode("utf-8") + b"a\xe9b\n")
        self.assertEqual(bad["line"], 2)

    def test_crlf_line_counting(self):
        bad = checker.check_bytes(
            b"name,city\r\nAna,Oslo\r\nBj\xf8rn,Bergen\r\n")
        self.assertEqual(bad["line"], 3)

    def test_nul_byte_is_valid_utf8(self):
        self.assertIsNone(checker.check_bytes(b"a\x00b\n"))

    def test_emoji_passes(self):
        self.assertIsNone(
            checker.check_bytes("mango \U0001f96d\n".encode("utf-8")))

    def test_check_text_helper(self):
        self.assertIsNone(checker.check_text("Ana,Oslo\n"))


class TestCLI(unittest.TestCase):
    def test_clean_file_exit_0(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "data.csv", "name,city\nAna,Oslo\n")
            code, out, err = run_cli([path])
            self.assertEqual(code, 0)
            self.assertIn("every file decodes as valid UTF-8", out)
            self.assertEqual(err, "")

    def test_flagged_file_exit_1_with_file_line_offset(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "data.csv",
                         b"name,city\nAna,Oslo\nBj\xf8rn,Bergen\n")
            code, out, err = run_cli([path])
            self.assertEqual(code, 1)
            self.assertIn("line 3", out)
            self.assertIn("offset 21", out)
            self.assertIn("not valid UTF-8", out)
            self.assertIn(path, out)

    def test_folder_walk_finds_csv_files_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "a.csv", "name\nAna\n")
            write(tmp, "b.csv", b"name\nBj\xf8rn\n")
            write(tmp, "notes.txt", b"name\nBj\xf8rn\n")
            code, out, err = run_cli([tmp])
            self.assertEqual(code, 1)
            self.assertIn("Checked 2 file(s)", out)
            self.assertIn("b.csv", out)
            self.assertNotIn("notes.txt", out)

    def test_folder_walk_skips_nested_with_no_recursive(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "a.csv", "name\nAna\n")
            write(tmp, "sub/b.csv", b"name\nBj\xf8rn\n")
            code, out, err = run_cli([tmp, "--no-recursive"])
            self.assertEqual(code, 0)
            self.assertIn("1 file(s) checked", out)
            code, out, err = run_cli([tmp])
            self.assertEqual(code, 1)
            self.assertIn("Checked 2 file(s)", out)

    def test_exclude_skips_a_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "a.csv", "name\nAna\n")
            write(tmp, "b.csv", b"name\nBj\xf8rn\n")
            code, out, err = run_cli([tmp, "--exclude", "b.csv"])
            self.assertEqual(code, 0)
            self.assertIn("1 file(s) checked", out)

    def test_git_folder_skipped_in_walk(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "a.csv", "name\nAna\n")
            write(tmp, ".git/b.csv", b"name\nBj\xf8rn\n")
            code, out, err = run_cli([tmp])
            self.assertEqual(code, 0)
            self.assertIn("1 file(s) checked", out)

    def test_direct_file_checked_whatever_its_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "export.txt", b"name\nBj\xf8rn\n")
            code, out, err = run_cli([path])
            self.assertEqual(code, 1)
            self.assertIn("export.txt", out)

    def test_duplicate_paths_checked_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "a.csv", "name\nAna\n")
            code, out, err = run_cli([path, path])
            self.assertEqual(code, 0)
            self.assertIn("1 file(s) checked", out)

    def test_case_insensitive_csv_extension(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "a.CSV", b"name\nBj\xf8rn\n")
            code, out, err = run_cli([tmp])
            self.assertEqual(code, 1)
            self.assertIn("a.CSV", out)

    def test_json_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "a.csv",
                         b"name\nBj\xf8rn\n")
            code, out, err = run_cli(["--json", path])
            self.assertEqual(code, 1)
            data = json.loads(out)
            self.assertEqual(data["checked"], 1)
            self.assertEqual(data["findings"], 1)
            self.assertEqual(data["files"][0]["path"], path)
            self.assertEqual(
                data["files"][0]["findings"][0]["line"], 2)
            self.assertIn("not valid UTF-8",
                          data["files"][0]["findings"][0]["reason"])
            self.assertIsNone(data["files"][0]["error"])

    def test_stdin_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, str(SRC), "--stdin"],
                input=b"name,city\nAna,Oslo\n", cwd=tmp,
                capture_output=True)
            self.assertEqual(result.returncode, 0)
            self.assertIn(b"every file decodes as valid UTF-8",
                          result.stdout)

    def test_stdin_dirty(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, str(SRC), "--stdin"],
                input=b"name,city\nAna,Oslo\nBj\xf8rn,Bergen\n",
                cwd=tmp, capture_output=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn(b"FAIL <stdin>:", result.stdout)
            self.assertIn(b"line 3", result.stdout)

    def test_stdin_with_paths_is_usage_error(self):
        code, out, err = run_cli(["--stdin", "data.csv"])
        self.assertEqual(code, 2)

    def test_no_paths_is_usage_error(self):
        code, out, err = run_cli([])
        self.assertEqual(code, 2)

    def test_missing_path_exit_2(self):
        code, out, err = run_cli(["no-such-folder-xyz"])
        self.assertEqual(code, 2)
        self.assertIn("no such file or folder", err)

    def test_empty_folder_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out, err = run_cli([tmp])
            self.assertEqual(code, 2)
            self.assertIn("no CSV files found", err)

    def test_bad_flag_exit_2(self):
        code, out, err = run_cli(["--nope"])
        self.assertEqual(code, 2)

    def test_version(self):
        code, out, err = run_cli(["--version"])
        self.assertEqual(code, 0)
        self.assertIn("csv_encoding_checker 1.0.0", out)

    def test_missing_file_reports_error(self):
        found, error = checker.check_file(
            os.path.join("no-such-dir", "gone.csv"))
        self.assertEqual(found, [])
        self.assertIn("cannot read file", error)

    def test_input_files_left_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "a.csv", b"name\nBj\xf8rn\n")
            before = Path(path).read_bytes()
            run_cli([path])
            self.assertEqual(Path(path).read_bytes(), before)

    def test_cli_runs_from_another_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "a.csv", "name\nAna\n")
            result = subprocess.run(
                [sys.executable, str(SRC), "a.csv"],
                cwd=tmp, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0)
            self.assertIn("every file decodes as valid UTF-8",
                          result.stdout)

    def test_cli_runs_under_fake_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "a.csv", "name\nAna\n")
            old_home = os.environ.get("HOME")
            os.environ["HOME"] = tmp
            try:
                code, out, err = run_cli([path])
            finally:
                if old_home is None:
                    del os.environ["HOME"]
                else:
                    os.environ["HOME"] = old_home
            self.assertEqual(code, 0)


class TestExamples(unittest.TestCase):
    def test_run_example_output_matches_sample(self):
        result = subprocess.run(
            ["sh", "examples/run-example.sh"],
            cwd=REPO, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        expected = (REPO / "examples/sample-output.md").read_text()
        self.assertEqual(result.stdout, expected)

    def test_readme_quotes_match_real_runs(self):
        readme = (REPO / "README.md").read_text()
        clean = subprocess.run(
            [sys.executable, "src/csv_encoding_checker.py",
             "examples/clean.csv"],
            cwd=REPO, capture_output=True, text=True)
        self.assertEqual(clean.returncode, 0)
        self.assertIn(clean.stdout.strip(), readme)
        flagged = subprocess.run(
            [sys.executable, "src/csv_encoding_checker.py",
             "examples/flagged.csv"],
            cwd=REPO, capture_output=True, text=True)
        self.assertEqual(flagged.returncode, 1)
        self.assertIn(flagged.stdout.strip(), readme)
        folder = subprocess.run(
            [sys.executable, "src/csv_encoding_checker.py",
             "examples/"],
            cwd=REPO, capture_output=True, text=True)
        self.assertEqual(folder.returncode, 1)
        self.assertIn("Checked 3 file(s), 1 file(s) failed.",
                      folder.stdout)
        self.assertIn("Checked 3 file(s), 1 file(s) failed.",
                      readme)
        edge = subprocess.run(
            [sys.executable, "src/csv_encoding_checker.py",
             "examples/edge.csv"],
            cwd=REPO, capture_output=True, text=True)
        self.assertEqual(edge.returncode, 0)
        self.assertIn(edge.stdout.strip(), readme)
        js = subprocess.run(
            [sys.executable, "src/csv_encoding_checker.py",
             "--json", "examples/flagged.csv"],
            cwd=REPO, capture_output=True, text=True)
        self.assertEqual(js.returncode, 1)
        self.assertIn(js.stdout.strip(), readme)
        stdin_run = subprocess.run(
            [sys.executable, "src/csv_encoding_checker.py",
             "--stdin"],
            cwd=REPO, input=b"name,city\nAna,Oslo\n"
                            b"Bj\xf8rn,Bergen\n",
            capture_output=True)
        self.assertEqual(stdin_run.returncode, 1)
        self.assertIn(stdin_run.stdout.decode().strip(), readme)


class TestHygiene(unittest.TestCase):
    def _repo_files(self, skip_tests=True, skip_examples=True):
        for root, dirs, files in os.walk(REPO):
            dirs[:] = [d for d in dirs
                       if d not in (".git", "__pycache__")
                       and not (skip_tests and d == "tests")
                       and not (skip_examples and d == "examples")]
            for name in files:
                if name.endswith(".pyc"):
                    continue
                yield Path(root) / name

    def test_no_placeholder_text(self):
        banned = ["TODO", "coming soon", "lorem", "FIXME", "XXX"]
        hits = []
        for path in self._repo_files(skip_tests=True,
                                     skip_examples=False):
            text = path.read_text(errors="ignore")
            for word in banned:
                if word in text:
                    hits.append("%s: %s" % (path.name, word))
        self.assertEqual(hits, [])

    def test_no_absolute_paths(self):
        # The markers are built without a literal temp-dir
        # path in this file, so the test itself stays clean.
        markers = ("/home/", "/Users/", "C:\\\\",
                   "/" + "tmp" + "/")
        hits = []
        for path in self._repo_files(skip_tests=True,
                                     skip_examples=False):
            text = path.read_text(errors="ignore")
            for marker in markers:
                if marker in text:
                    hits.append("%s: %s" % (path.name, marker))
        self.assertEqual(hits, [])

    def test_no_real_secrets_outside_tests_and_examples(self):
        # The source holds no key values at all; the tests
        # and examples hold fake values only, so they are
        # excluded from this scan.
        patterns = [
            re.compile(r"AKIA[0-9A-Z]{16}"),
            re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
            re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
            re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
            re.compile(r"AIza[0-9A-Za-z_-]{35}"),
            re.compile(r"[rs]k_(?:live|test)_[A-Za-z0-9]{16,}"),
            re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
            re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ"),
        ]
        hits = []
        for path in self._repo_files():
            text = path.read_text(errors="ignore")
            for pattern in patterns:
                if pattern.search(text):
                    hits.append("%s: %s" % (path.name, pattern.pattern))
        self.assertEqual(hits, [])

    def test_stdlib_imports_only(self):
        stdlib = set(sys.stdlib_module_names)
        for target in (REPO / "src/csv_encoding_checker.py",
                       REPO / "tests/test_csv_encoding_checker.py"):
            tree = ast.parse(target.read_text())
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(a.name.split(".")[0]
                                    for a in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split(".")[0])
            self.assertFalse(
                imported - stdlib - {"csv_encoding_checker"},
                (target.name, imported))
            self.assertNotIn("yaml", imported)

    def test_no_network_use_in_src(self):
        src = (REPO / "src/csv_encoding_checker.py").read_text()
        for marker in ("urllib.request", "requests", "socket",
                       "http.client", "urlopen", "urlretrieve"):
            self.assertNotIn(marker, src, marker)

    def test_gitignore_lists_env_first(self):
        lines = (REPO / ".gitignore").read_text().splitlines()
        self.assertEqual(lines[0], ".env")

    def test_ci_runs_this_test_file(self):
        ci = (REPO / ".github/workflows/ci.yml").read_text()
        self.assertIn("tests/test_csv_encoding_checker.py", ci)
        self.assertIn("ubuntu-latest", ci)
        self.assertIn("3.12", ci)
        self.assertIn("actions/checkout", ci)
        self.assertIn("setup-python", ci)
        self.assertIn("push", ci)
        self.assertIn("pull_request", ci)

    def test_readme_names_the_neighbouring_repos(self):
        readme = (REPO / "README.md").read_text()
        self.assertIn("csv-bom-checker-cli", readme)
        self.assertIn("csv-column-count-checker-cli", readme)
        self.assertIn("csv-header-checker-cli", readme)


if __name__ == "__main__":
    unittest.main()
