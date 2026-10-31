Read [the rules for contributions](https://github.com/mchojna/factory-simulator/blob/main/CONTRIBUTING.md)
before you open a pull request.

## What this changes

<!-- One or two sentences. What is different after this is merged, stated as a fact. -->

## Issue

<!-- The issue this pull request closes, as `Closes #N`. -->

## Checklist

- [ ] The title is a Conventional Commit: `type(scope): subject`, imperative, lower
      case, no full stop. Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`,
      `perf`, `build`, `ci`. A breaking change adds `!` before the colon.
- [ ] `uv run pre-commit run --all-files` and `uv run pytest` pass locally.
- [ ] Every new module, class and public function has a Google docstring with a
      runnable example.
- [ ] Every new rule has a unit test with a value computed by hand and, where the rule
      holds for every input, a Hypothesis test.

## Notes for the reviewer

<!-- Anything that would take the reviewer more than a minute to work out alone. -->
