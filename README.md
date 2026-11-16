# csv-encoding-checker-cli

Check CSV files decode as valid UTF-8 — fail CI when one does not.

[![CI](https://github.com/haiderstudio/csv-encoding-checker-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/haiderstudio/csv-encoding-checker-cli/actions/workflows/ci.yml) [![Licence: MIT](https://img.shields.io/badge/Licence-MIT-yellow.svg)](LICENSE)

## What it does

`csv_encoding_checker` reads each CSV file as bytes,
tries to decode it as UTF-8, and reports each file
that fails, with the file and the line of the first
bad byte. It exits 1 when any file fails to decode,
so it can fail a CI run. A file that decodes cleanly
exits 0.

- A CSV saved in the wrong encoding — a Windows-1252
  export, a Latin-1 dump — breaks the import or turns
  names into mojibake, and the file looks fine in the
  editor that saved it. This names the exact line and
  byte offset, and the fix is one re-save per file.
- A UTF-8 byte order mark (BOM) decodes fine, so a
  file with a BOM passes here. The BOM itself is a
  separate concern — repo #105, csv-bom-checker-cli,
  checks for one. This tool only reports bytes that
  cannot be decoded as UTF-8 at all.
- A file given directly on the command line is always
  checked, whatever its name. A folder is walked for
  files ending in `.csv` only, recursively by default
  (`--no-recursive` stops at the top level). `.git`
  folders are never walked, and directory links are
  never followed.
- `--json` prints the result as JSON, and `--stdin`
  checks one CSV document read from standard input.

## Who it is for

Anyone who ships CSV data files — a shop exporting
orders, a team sharing a customer list, a pipeline
that feeds a CSV into a database. One wrong-encoding
export and the import breaks or names come out as
mojibake, and the file looks fine on the machine that
saved it. This is the gate that stops it at the pull
request.

## What it does NOT do

- It does not check for a BOM. That is repo #105,
  csv-bom-checker-cli — a BOM is a different check on
  the same files.
- It does not check the CSV structure — headers,
  column counts, quoting, or duplicate rows. Those
  are repo #40, csv-header-checker-cli, repo #58,
  csv-column-count-checker-cli, repo #80,
  csv-quote-checker-cli, and repo #84,
  csv-duplicate-row-checker-cli — structure is a
  different check on the same files.
- It does not check which encoding a file actually
  is, and it does not convert anything. It only
  answers one question: does this file decode as
  UTF-8?
- It never rewrites a file, and it never touches the
  network.

## How this differs

- A fresh search of GitHub on Nov 15, 2026 found 0
  results for `"csv-encoding-checker-cli"` and 3
  results for `csv encoding checker` — all noise:
  cart231-ffly-b/jp-csv-traps-free, 0 stars (Japanese
  CSV test files with a parser checker — test data,
  not a gate); garyjob/network_checker, 0 stars (a
  grab-bag of tools — port, SSL, and CSV encoding
  checks in one, no standalone CLI gate for CSV
  encoding); ManojKumarPatnaik/Major-project-list,
  262 stars (a list of practice projects for
  students, not a checker of any kind).
- No rival is a tested stdlib CLI gate for CSV
  encoding.

## Install

```sh
git clone https://github.com/haiderstudio/csv-encoding-checker-cli.git
cd csv-encoding-checker-cli
```

There is nothing else to install: Python 3.10 or newer,
standard library only, no dependencies.

## Usage

Check one CSV file:

```sh
python3 src/csv_encoding_checker.py data.csv
```

A file that decodes as valid UTF-8 passes:

```sh
$ python3 src/csv_encoding_checker.py examples/clean.csv
OK — 1 file(s) checked, every file decodes as valid UTF-8.
```

A file with undecodable bytes fails, with the file,
the byte offset, and the line:

```sh
$ python3 src/csv_encoding_checker.py examples/flagged.csv
FAIL examples/flagged.csv: is not valid UTF-8 (first bad byte at offset 32, line 3)
Checked 1 file(s), 1 file(s) failed.
```

Check a whole folder (`.csv` files only):

```sh
$ python3 src/csv_encoding_checker.py examples/
FAIL examples/flagged.csv: is not valid UTF-8 (first bad byte at offset 32, line 3)
Checked 3 file(s), 1 file(s) failed.
```

Check one document from standard input:

```sh
$ printf 'name,city\nAna,Oslo\nBj\xf8rn,Bergen\n' | python3 src/csv_encoding_checker.py --stdin
FAIL <stdin>: is not valid UTF-8 (first bad byte at offset 21, line 3)
Checked 1 file(s), 1 file(s) failed.
```

Machine-readable output:

```sh
$ python3 src/csv_encoding_checker.py --json examples/flagged.csv
{
  "files": [
    {
      "path": "examples/flagged.csv",
      "findings": [
        {
          "line": 3,
          "reason": "is not valid UTF-8 (first bad byte at offset 32, line 3)"
        }
      ],
      "error": null
    }
  ],
  "checked": 1,
  "findings": 1
}
```

Exit codes: 0 when every file decodes as UTF-8, 1
when any file fails to decode or a file cannot be
read, 2 for a usage error (a missing path, a bad
flag, or no CSV files found).

## Examples

A file with accented names in proper UTF-8 passes —
`examples/clean.csv` holds José, Müller, and Anaïs:

```sh
$ python3 src/csv_encoding_checker.py examples/clean.csv
OK — 1 file(s) checked, every file decodes as valid UTF-8.
```

A BOM, an emoji, and a quoted field split across
lines are all valid UTF-8 — `examples/edge.csv` has
all of them, and it passes:

```sh
$ python3 src/csv_encoding_checker.py examples/edge.csv
OK — 1 file(s) checked, every file decodes as valid UTF-8.
```

A single Latin-1 byte is enough to fail a file — the
`ø` in `examples/flagged.csv` is one byte, 0xF8,
where UTF-8 would need two:

```sh
$ python3 src/csv_encoding_checker.py examples/flagged.csv
FAIL examples/flagged.csv: is not valid UTF-8 (first bad byte at offset 32, line 3)
Checked 1 file(s), 1 file(s) failed.
```

Run every bundled example at once with `sh
examples/run-example.sh` — the output is saved in
[examples/sample-output.md](examples/sample-output.md).

## How it is tested

```sh
python3 tests/test_csv_encoding_checker.py
```

The tests cover decode detection (clean ASCII passes,
clean multibyte passes, an empty file passes, a BOM
only passes, a BOM then clean text passes, a bad byte
on line 1, a bad byte on line 3 with its offset, the
first bad byte reported when several are present, a
lone continuation byte fails, a truncated multibyte
at the end fails, a bad byte after valid multibyte
text, CRLF line counting, a NUL byte passes, an
emoji passes), the CLI (exit 0/1/2, folder walking
for several CSV files including `.CSV`, nested
folders, `--no-recursive`, `--exclude`, `.git`
skipped, a direct file checked whatever its name,
duplicate paths checked once, `--json` output,
`--stdin`, bad flags, missing paths, empty folders,
`--version`, a missing file reported, input files
left unchanged, the tool run from another folder and
under a changed HOME), the bundled examples (sample
output compared byte-for-byte against a fresh run,
and the README-quoted outputs checked against it),
and hygiene checks (no placeholder text, no absolute
paths, no real secrets outside the tests and
examples, stdlib imports only, no network use in the
source, `.env` first in `.gitignore`, CI file runs
the test file, README names the neighbouring repos).

## Contributing

Small, focused improvements are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

MIT — see [LICENSE](LICENSE).

## Original work

This tool was written from scratch for this repo. The
idea of checking a file's encoding is not new, and
decoding follows Python's own standard-library UTF-8
decoder — but no existing tool does this one job,
checking that CSV files in local folders decode as
UTF-8, as a tested command-line gate with a CI exit
code, as the search above shows — and every line of
code here is original, built on nothing but Python's
standard library.
