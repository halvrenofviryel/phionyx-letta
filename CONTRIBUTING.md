# Contributing to `phionyx-letta`

`phionyx-letta` is a Letta memory-mutation evidence-envelope builder for the Phionyx runtime-evidence layer. It is **alpha / experimental**. Contributions, independent
implementations, and adversarial critique are welcome — especially an independent party
reproducing what this package claims, or a test that makes a check fail when it should.

## Ground rules

1. **Claim ≤ Evidence.** Every claim in the README, docstrings, or docs must match what the code
   actually does. Use the weakest accurate word: not "trusted"/"verified"/"production-ready" above
   what is measured. Regulatory or standards anchors are **INDICATIVE** until checked against the
   primary source. A PR that raises a claim without raising the evidence will be asked to lower the
   claim or add the evidence.
2. **Honest failure states.** A check must distinguish pass from fail from "not measured". Do not
   map an unmeasured, errored, or inconclusive result to success. New checks should be **total**
   over malformed input (return a verdict, never crash).
3. **Tests move with behavior.** Any behavior change comes with a test that proves it, and a
   negative test where a gate is involved (bad input → rejected). New public behavior needs at
   least one test demonstrating it.
4. **Keep the scope honest.** If the package "does not do X", the README says so; don't quietly
   imply more. Do not add a dependency without a reason.

## How to propose a change

- Open an issue describing the change and its impact. For a bug, include a minimal reproduction.
- Keep PRs focused; explain what changed, what you tested, and what risk remains.

## Before you open a PR

```bash
pip install -e ".[test]"    # or ".[dev]" where present
pytest -q                    # all tests pass, no new failures
```

If the project declares `ruff` / `mypy` in its optional extras, run them too:

```bash
ruff check . && mypy .       # where configured
```

## Conduct

Be precise, be kind, assume good faith. Disagreements are resolved by what the tests and the
evidence actually demonstrate, not by authority. Do not put personal data, secrets, or credentials
in commits, issues, or PRs.

## License of contributions

This project is licensed **AGPL-3.0-or-later**. By contributing, you agree your contributions are
licensed under the same terms.