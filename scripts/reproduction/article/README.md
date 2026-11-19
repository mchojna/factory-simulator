# Article examples and figures

These commands reproduce the controlled examples in Sections 3.1-3.3 and draw
Figures 1-6 from the archived data. The simulator and LLM client stay in this
repository. The separate data archive contains no executable code.

Start with [the reproduction guide](../README.md) to obtain the matching code and
check and extract `Factory-Simulator-Reproduction.zip` placed beside the checkout.
Run commands from the repository root:

```sh
PACKAGE=data/reproduction/Factory-Simulator-Reproduction
uv run python -m scripts.reproduction.article all \
  --data "$PACKAGE" --output data/article-check
```

Use a new output directory. Input data are checked against their manifest before
execution and checked again afterwards. Output cannot be inside the data folder.
The command refuses Python's `-O` mode, because scientific checks use assertions.
Network sockets are blocked, and no command imports a hosted-model provider.

The `all` command executes, in order:

| Group | Procedure | Check |
| --- | --- | --- |
| `notice` | 34 archived notice-matrix cases | Material/financial balances, accepted decisions, matched physical worlds |
| | Six reconstructed planning questions, seven solves each | Constraint residuals, integrality and objective reconciliation |
| | One controlled continuation from an equal-valued decision | Same prefix and world; recorded outcomes |
| | 12 archived storage-sensitivity cases | Same worlds and balances |
| | Comparison with the archived evidence | Exact JSON results, periods and worlds; diagnostic tolerance 1e-7 with elapsed timings excluded |
| `examples` | Seven fulfilment/fork/replay/disclosure executions | Balances, common prefix, replay and archived JSON outcomes |
| | Seven micro-allocation executions | Enumerated alternatives and the recorded optimum 0.059 |
| `figures` | Figures 1-6, each as PNG, SVG and PDF | Rendered from archived inputs, without rerunning controllers |

Each group is also a command, for example `article figures --data ... --output ...`.
The groups write to `notice/`, `examples/` and `figures/` in the output folder.
`example-comparison.json` and `notice/verification.json` contain the comparisons.
Both verifiers require the complete archived set: missing or extra example JSON
records, notice case identifiers or notice record files fail the check. Known
example timing/environment summaries are excluded by their exact relative paths.
Figure generation isolates Figure 5's style from the preceding plots.
The nine procedures are adaptations of the article's original scripts: path handling,
explicit imports, guarded entry points and result checks changed; factory parameters,
controller settings and archived outcomes did not. The scripts reuse `tests/factories`
from this checkout. They do not use a second source tree embedded in the archive.

A failed equality check must be investigated and retained, not resolved by replacing
the archived expectation. Re-optimisation can choose different equal-valued plans on
another solver/platform. Saved-action replay is a separate check and does not solve
optimisation problems. Historical source fingerprints describe the original code;
current before/after fingerprints check that execution did not alter this checkout.
This command does not rerun the stress campaign or the four 52-period reference
optimisations, and does not generate new LLM responses.
