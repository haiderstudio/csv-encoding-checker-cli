#!/usr/bin/env python3
"""Check CSV files decode as valid UTF-8.

Run: python3 src/csv_encoding_checker.py data.csv
     python3 src/csv_encoding_checker.py data/
     python3 src/csv_encoding_checker.py --stdin < data.csv

A CSV saved in the wrong encoding — a Windows-1252
export, a Latin-1 dump — breaks the import or turns
names into mojibake, and the file looks fine in the
editor that saved it. This tool reads each CSV file
as bytes, tries to decode it as UTF-8, and reports
each file that fails, with the file and the line of
the first bad byte. It exits 1 when any file fails
to decode, so it can fail a CI run. A file that
decodes cleanly exits 0.

A UTF-8 byte order mark (BOM) decodes fine, so a
file with a BOM passes here. The BOM itself is a
separate concern — repo #105, csv-bom-checker-cli,
checks for one. This tool only reports bytes that
cannot be decoded as UTF-8 at all.

A file given directly on the command line is always
checked, whatever its name. A folder is walked for
files ending in .csv only, recursively by default
(--no-recursive stops at the top level). .git
folders are never walked, and directory links are
never followed.

It never rewrites a file, never touches the network,
and reads only the files and folders you point it at.
"""

import argparse
import fnmatch
import json
import os
import sys

VERSION = "1.0.0"
EXTENSIONS = (".csv",)


def check_bytes(data):
    """Return a finding dict for undecodable bytes, else None.

    The finding names the line holding the first bad
    byte, counted from 1, and the byte offset of that
    byte from the start of the file.
    """
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as exc:
        line = data[:exc.start].count(b"\n") + 1
        return {
            "line": line,
            "reason": (
                "is not valid UTF-8 (first bad byte at "
                "offset %d, line %d)" % (exc.start, line)
            ),
        }
    return None


def check_text(text):
    """Check one CSV document given as text (UTF-8 already).

    Text that is already a Python string has decoded,
    so there is nothing to fail. This helper exists so
    tests can call the checker on plain strings.
    """
    return check_bytes(text.encode("utf-8"))


def check_file(path):
    """Check one file. Return (findings, error).

    findings is a list of finding dicts (at most one:
    a file either decodes or it does not). error is a
    string when the file cannot be read, else None.
    """
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError as exc:
        return [], "cannot read file: %s" % exc.strerror
    finding = check_bytes(data)
    return ([finding] if finding else []), None


def collect_files(paths, recursive, exclude):
    """Expand command-line paths into a sorted file list.

    Files are checked in the order given, each path
    once. Folders contribute their .csv files only.
    Returns (files, error): error names the first
    problem (a missing path, or no CSV files found).
    """
    files = []
    seen = set()
    for path in paths:
        if os.path.isfile(path):
            real = os.path.realpath(path)
            if real not in seen:
                seen.add(real)
                files.append(path)
        elif os.path.isdir(path):
            for root, dirs, names in os.walk(path,
                                            followlinks=False):
                dirs[:] = sorted(
                    d for d in dirs if d != ".git")
                if not recursive:
                    dirs[:] = []
                for name in sorted(names):
                    if not name.lower().endswith(EXTENSIONS):
                        continue
                    if any(fnmatch.fnmatch(name, pattern)
                           for pattern in exclude):
                        continue
                    full = os.path.join(root, name)
                    real = os.path.realpath(full)
                    if real not in seen:
                        seen.add(real)
                        files.append(full)
        else:
            return [], "no such file or folder: %s" % path
    if not files:
        return [], "no CSV files found"
    return files, None


def report_text(results, checked, findings):
    """Build the plain-text report for a run."""
    lines = []
    for result in results:
        path = result["path"]
        if result["error"]:
            lines.append("ERROR %s: %s" % (path, result["error"]))
        for finding in result["findings"]:
            lines.append("FAIL %s: %s" % (path, finding["reason"]))
    bad = sum(1 for r in results
              if r["findings"] or r["error"])
    if bad:
        lines.append(
            "Checked %d file(s), %d file(s) failed."
            % (checked, bad))
    else:
        lines.append(
            "OK \u2014 %d file(s) checked, every file decodes "
            "as valid UTF-8." % checked)
    return "\n".join(lines) + "\n"


def report_json(results, checked, findings):
    """Build the JSON report for a run."""
    return json.dumps({
        "files": results,
        "checked": checked,
        "findings": findings,
    }, indent=2) + "\n"


def main(argv=None):
    """Entry point. Returns an exit code (0, 1, or 2)."""
    parser = argparse.ArgumentParser(
        prog="csv_encoding_checker",
        description="Check CSV files decode as valid UTF-8.")
    parser.add_argument("paths", nargs="*", metavar="PATH",
                        help="CSV file or folder to check")
    parser.add_argument("--no-recursive", action="store_true",
                        help="do not walk into subfolders")
    parser.add_argument("--exclude", action="append",
                        default=[],
                        metavar="PATTERN",
                        help="skip files matching this glob pattern "
                             "(repeatable)")
    parser.add_argument("--json", action="store_true",
                        help="print the result as JSON")
    parser.add_argument("--stdin", action="store_true",
                        help="check one CSV document from stdin")
    parser.add_argument("--version", action="version",
                        version="csv_encoding_checker " + VERSION)
    args = parser.parse_args(argv)

    if args.stdin:
        if args.paths:
            print("error: --stdin takes no paths",
                  file=sys.stderr)
            return 2
        data = sys.stdin.buffer.read()
        finding = check_bytes(data)
        results = [{"path": "<stdin>",
                    "findings": [finding] if finding else [],
                    "error": None}]
        checked = 1
        findings = 1 if finding else 0
        bad = findings
    else:
        if not args.paths:
            print("error: give a CSV file or folder to check",
                  file=sys.stderr)
            return 2
        files, error = collect_files(
            args.paths, not args.no_recursive, args.exclude)
        if error:
            print("error: %s" % error, file=sys.stderr)
            return 2
        results = []
        findings = 0
        bad = 0
        for path in files:
            found, err = check_file(path)
            if found or err:
                bad += 1
            findings += len(found)
            results.append({"path": path, "findings": found,
                            "error": err})
        checked = len(files)

    if args.json:
        sys.stdout.write(report_json(results, checked, findings))
    else:
        sys.stdout.write(report_text(results, checked, findings))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
