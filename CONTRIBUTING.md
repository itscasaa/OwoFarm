# Contributing to Mizu OwO

Thanks for helping improve Mizu OwO. This guide covers everything you need to get started.

## Ways to Contribute

- Report bugs
- Suggest features
- Fix bugs or add features
- Improve documentation
- Write or improve tests

## Reporting Bugs

Before opening an issue, check [existing issues](https://github.com/kiy0w0/owomizu/issues) and make sure you are on the latest version.

Include:
- What happened and what you expected
- Steps to reproduce
- Your OS, Python version, and bot version (`git log --oneline -1`)
- Relevant logs or screenshots

For security issues, do not post publicly. Email hello@kuromi.foo instead.

## Suggesting Features

Search existing requests first. When you open one, describe the problem it solves, your proposed solution, and who would use it.

## Development Setup

Requires Python 3.11 or 3.12 (CI runs on 3.10 and 3.11).

```bash
git clone https://github.com/kiy0w0/owomizu.git
cd owomizu
pip install -r requirements.txt

# Put your Discord token in .env, then adjust config/*.json as needed
python mizu.py
```

## Workflow

1. Fork and clone the repo
2. Create a branch: `feature/description` or `fix/description`
3. Make your changes and add tests
4. Run the test suite and linter
5. Commit and open a pull request

```bash
git checkout -b feature/my-change
# make changes

python tests/run_tests.py
flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics

# stage only what you changed, never "git add ."
git add path/to/file.py
git commit -m "update my change"
git push origin feature/my-change
```

Do not use `git add .`. The repo holds local runtime data (`utils/stats.json`, `utils/data/*`, `db.sqlite-*`) that must never be committed.

## Coding Standards

- Follow PEP 8, max line length 127 (matches flake8 CI)
- Use double quotes and type hints where practical
- Keep functions small and readable

## Testing

Tests are plain `test_*` functions, no classes and no pytest. Each module lives in `tests/` and must be registered in the `TEST_MODULES` list in `tests/run_tests.py`, or it will not run.

```python
from utils.danger import load_danger, is_allowed


def test_gate_defaults_off():
    danger = load_danger()
    assert is_allowed(danger, "allowAutoQuest") is False
```

Run the full suite before opening a PR:

```bash
python tests/run_tests.py
```

## Pull Requests

Before submitting, make sure:

- [ ] Branch is named `feature/...` or `fix/...`
- [ ] Tests are added and registered in `tests/run_tests.py`
- [ ] `python tests/run_tests.py` passes
- [ ] `flake8` reports no E9/F63/F7/F82 errors
- [ ] No personal data staged (`utils/stats.json`, `utils/data/*`)
- [ ] Docs updated if behavior changed

Keep the PR title short and describe what changed and why. Link related issues with `Closes #123`.

## Community

Be respectful, patient, and constructive. Harassment, spam, and personal attacks are not tolerated.

Questions? Join the [Discord](https://discord.gg/bkvMhwjSPG) or open a [GitHub Discussion](https://github.com/kiy0w0/owomizu/discussions).
