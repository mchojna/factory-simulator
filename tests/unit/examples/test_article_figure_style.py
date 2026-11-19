import json
from pathlib import Path

import matplotlib
import pytest

from scripts.reproduction.article import context, make_figure5


def test_figure5_is_independent_of_previous_style(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    data = tmp_path / "data"
    (data / "notice").mkdir(parents=True)
    cases = {
        f"library_like-notice{n}-{controller}": {
            "profit": "1766.084",
            "measures": {"units_shipped_on_time": 40},
        }
        for n in (0, 2)
        for controller in ("rolling", "buffered", "full_horizon", "reference")
    }
    (data / "notice/recorded-results.json").write_text(json.dumps({"cases": cases}))
    monkeypatch.setattr(context, "DATA", data)
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "cache"))
    monkeypatch.setattr(context, "OUTPUT", tmp_path / "standalone")
    with matplotlib.rc_context(rc=matplotlib.rcParamsDefault):  # pyright: ignore[reportUnknownMemberType]
        make_figure5.main()
    monkeypatch.setattr(context, "OUTPUT", tmp_path / "batch")
    with matplotlib.rc_context(  # pyright: ignore[reportUnknownMemberType]
        {"text.color": "#18384c", "axes.labelcolor": "red", "font.size": 23}
    ):
        make_figure5.main()
        assert matplotlib.rcParams["text.color"] == "#18384c"
        assert matplotlib.rcParams["axes.labelcolor"] == "red"
        assert matplotlib.rcParams["font.size"] == 23
    assert (tmp_path / "standalone/figures/figure-5.png").read_bytes() == (
        tmp_path / "batch/figures/figure-5.png"
    ).read_bytes()
