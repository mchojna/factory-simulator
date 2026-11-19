# Examples unit tests

These tests cover the shared model settings, the hosted providers and the coordinated
planning example.

## Contents

- [test_article_completeness.py](test_article_completeness.py): the article verifiers
  require complete example records and notice cases.
- [test_article_figure_style.py](test_article_figure_style.py): Figure 5 does not
  depend on the plotting style left by earlier figures.
- [test_article_paths.py](test_article_paths.py): the article commands refuse output
  inside the data, reused output and modified data.
- [test_coordinated_agent.py](test_coordinated_agent.py): the reviewer repairs, the
  filter and the check outcomes of the coordinated agent.
- [test_coordinated_command.py](test_coordinated_command.py): the evidence archive, the
  recorded provider and the modes of the command.
- [test_coordinated_transport.py](test_coordinated_transport.py): the budget, the
  retries and the deadline of the live provider.
- [test_model.py](test_model.py): the model settings tests.
- [test_providers.py](test_providers.py): hosted provider request, response and error checks.

## Entry point

Start with [test_model.py](test_model.py).
