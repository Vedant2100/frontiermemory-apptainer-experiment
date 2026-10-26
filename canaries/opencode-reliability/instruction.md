Implement a tiny standalone greeting feature in this disposable repository.

Create `/app/canary_greeting.py` with `greet(name: str) -> str`. It must trim leading and trailing whitespace and return `Hello, {trimmed_name}!`. If the trimmed name is empty, raise `ValueError`.

Create `/app/test_canary_greeting.py` with `unittest` tests for a normal name, a whitespace-padded name, and an empty/whitespace-only name.

For this tool-reliability canary, create both new files using Bash heredocs (or OpenCode's native write tool); do not use exact-match edit on a new file. Run `python3 -m unittest -v test_canary_greeting.py` from `/app`, inspect `git diff` and `git status`, and leave the files uncommitted so Harbor's dirty-tree collector is exercised. Do not modify existing cattrs source files.
