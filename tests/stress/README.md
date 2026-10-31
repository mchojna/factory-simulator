# Stress tests

The stress test plays no decisions and the benchmark agents across the scenarios of the
example manifest over many seeds, checks every run and writes a report into
`data/reports/`. It starts by hand with `uv run pytest tests/stress -m stress -n 0`;
[the stress test page](../../docs/development/en/benchmark/stress-test.md) lists its
options and their defaults. The other tests here check its parts with worked examples
and properties.

## Contents

- [__init__.py](__init__.py): the stress test package.
- [checks.py](checks.py): decision, accounting and completed-run checks.
- [controls.py](controls.py): information controls and quantities held equal.
- [playing.py](playing.py): optimizer execution and recorded run rows.
- [protocol.py](protocol.py): the calibration protocol, its frozen definitions and the
  record of evaluation starts.
- [report.py](report.py): paired scores, intervals, tables and the score chart.
- [scale.py](scale.py): the scale study, generated manifests by pattern of counts with
  their economic profile and scores.
- [test_checks.py](test_checks.py): worked examples and properties of run checks.
- [test_controls.py](test_controls.py): worked examples and properties of information
  controls.
- [test_playing.py](test_playing.py): worked examples and properties of optimizer
  execution and row selection.
- [test_protocol.py](test_protocol.py): worked examples of the calibration protocol and
  its refusals.
- [test_report.py](test_report.py): worked examples and properties of scores, tables
  and the rendered chart.
- [test_scale.py](test_scale.py): worked examples of the scale protocol checks and the
  scale tables.
- [test_selection.py](test_selection.py): the marker expressions that select the stress
  test.
- [test_stress.py](test_stress.py): the stress test itself.

## Entry point

Start with [test_stress.py](test_stress.py).
