"""Console output shared by standalone developer commands."""

import sys
from typing import TextIO, cast


def console(*values: object, file: TextIO | None = None) -> None:
    """Write a space-separated line to the selected console stream."""
    stream = file if file is not None else cast("TextIO", sys.stdout)
    stream.write(" ".join(str(value) for value in values) + "\n")
