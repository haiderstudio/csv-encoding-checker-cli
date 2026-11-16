# Security Policy

This tool runs locally, collects no data, sends nothing anywhere, and needs no API key or secret. It only reads the CSV files you point it at, and it never rewrites a file and never changes anything. It writes nothing except the report on standard output (and usage errors on standard error). It never fetches a URL and never runs a command.

It only checks that a CSV file decodes as valid UTF-8. It never parses the CSV rows, never sends the contents anywhere, and never runs anything inside the file.

If you find a case where the tool rewrites a file, opens a URL, or reports a pass for a CSV file that does not decode as UTF-8, please open an issue describing the exact commands and input. Do not include any real secret in the report.
