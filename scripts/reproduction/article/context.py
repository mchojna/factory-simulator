"""Paths for the article commands; input data are never modified."""

import os
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[3]
DATA = Path(
    os.environ.get(
        "FACTORY_ARTICLE_DATA", "data/reproduction/Factory-Simulator-Reproduction"
    )
).resolve()
OUTPUT = Path(os.environ.get("FACTORY_ARTICLE_OUTPUT", "data/article-output")).resolve()
