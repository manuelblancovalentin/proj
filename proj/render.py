"""Terminal output for proj: boxed, colored tables on a terminal, plain
columns when piped. Standard library only."""

from __future__ import annotations

import os
import re
import shutil
import sys
import textwrap
from typing import Sequence, TextIO

RESET = "\033[0m"
STYLES = {
    "bold": "\033[1m",
    "dim": "\033[2m",
    "cyan": "\033[36m",
    "yellow": "\033[33m",
    "green": "\033[32m",
    "magenta": "\033[35m",
    "red": "\033[31m",
}
_ANSI = re.compile(r"\033\[[0-9;]*m")

UNICODE_BOX = dict(h="─", v="│", tl="╭", tr="╮", bl="╰", br="╯", lj="├", rj="┤", cj="┼")
ASCII_BOX = dict(h="-", v="|", tl="+", tr="+", bl="+", br="+", lj="+", rj="+", cj="+")


def visible_length(text: str) -> int:
    return len(_ANSI.sub("", text))


class Output:
    """Decides once whether output is fancy (terminal) or plain (piped).

    PROJ_COLOR=always|never overrides detection; NO_COLOR and TERM=dumb
    disable it. The keyword arguments exist for tests.
    """

    def __init__(
        self,
        stream: TextIO | None = None,
        mode: str | None = None,
        width: int | None = None,
        unicode: bool | None = None,
    ):
        stream = stream or sys.stdout
        mode = mode or os.environ.get("PROJ_COLOR", "auto")
        if mode == "always":
            self.fancy = True
        elif mode == "never":
            self.fancy = False
        else:
            self.fancy = (
                stream.isatty()
                and not os.environ.get("NO_COLOR")
                and os.environ.get("TERM") != "dumb"
            )
        encoding = (getattr(stream, "encoding", None) or "").lower()
        self.unicode = self.fancy and ("utf" in encoding if unicode is None else unicode)
        self.width = max(60, width or shutil.get_terminal_size((100, 24)).columns)

    # --- text ------------------------------------------------------------

    def paint(self, text: str, *styles: str) -> str:
        if not self.fancy or not styles or not text:
            return text
        return "".join(STYLES[name] for name in styles) + text + RESET

    def heading(self, text: str) -> str:
        return self.paint(text, "bold", "yellow")

    def note(self, text: str) -> str:
        """Secondary text; wrapped to the terminal when output is fancy."""
        if self.fancy:
            text = textwrap.fill(
                text, self.width - 1, break_long_words=False, break_on_hyphens=False
            )
            return "\n".join(self.paint(line, "dim") for line in text.splitlines())
        return text

    # --- tables ----------------------------------------------------------

    def table(
        self,
        headers: Sequence[str],
        rows: Sequence[Sequence[str]],
        *,
        title: str | None = None,
        flex: int | None = None,
        styles: Sequence[Sequence[str]] | None = None,
    ) -> list[str]:
        """Lines of a table. flex is the column that wraps when space is short."""
        if not self.fancy:
            return self._plain(headers, rows, title)
        return self._boxed(headers, rows, title, flex, styles)

    def _plain(self, headers, rows, title) -> list[str]:
        widths = [
            max([len(header)] + [len(row[index]) for row in rows])
            for index, header in enumerate(headers)
        ]

        def line(values) -> str:
            return "  ".join(value.ljust(width) for value, width in zip(values, widths)).rstrip()

        lines = [title] if title else []
        lines.append(line(headers))
        lines.append("  ".join("-" * width for width in widths))
        lines.extend(line(row) for row in rows)
        return lines

    def _boxed(self, headers, rows, title, flex, styles) -> list[str]:
        box = UNICODE_BOX if self.unicode else ASCII_BOX
        columns = len(headers)
        widths = [
            max([len(header)] + [len(part) for row in rows for part in row[index].split("\n")])
            for index, header in enumerate(headers)
        ]
        available = self.width - (3 * columns + 1)
        if flex is not None and sum(widths) > available:
            others = sum(widths) - widths[flex]
            widths[flex] = max(12, available - others, len(headers[flex]))

        def cell_lines(row) -> list[list[str]]:
            result = []
            for index, value in enumerate(row):
                if index == flex:
                    wrapped = []
                    for part in value.split("\n"):
                        wrapped.extend(
                            textwrap.wrap(
                                part,
                                widths[index],
                                break_long_words=True,
                                break_on_hyphens=False,
                            )
                            or [""]
                        )
                    result.append(wrapped)
                else:
                    result.append(value.split("\n"))
            return result

        column_styles = [tuple(item) for item in (styles or [])]
        column_styles += [()] * (columns - len(column_styles))

        def render(values, cell_styles) -> str:
            cells = [
                self.paint(value.ljust(width), *style)
                for value, width, style in zip(values, widths, cell_styles)
            ]
            return f"{box['v']} " + f" {box['v']} ".join(cells) + f" {box['v']}"

        inner = sum(widths) + 3 * columns - 1
        if title and inner < len(title) + 4:
            widths[-1] += len(title) + 4 - inner
            inner = len(title) + 4
        if title:
            label = f" {title} "
            top = (
                self.paint(box["tl"] + box["h"], "dim")
                + self.heading(label)
                + self.paint(box["h"] * (inner - 1 - len(label)) + box["tr"], "dim")
            )
        else:
            top = self.paint(box["tl"] + box["h"] * inner + box["tr"], "dim")
        lines = [top]
        lines.append(render(headers, [("bold", "cyan")] * columns))
        lines.append(
            box["lj"] + box["cj"].join(box["h"] * (width + 2) for width in widths) + box["rj"]
        )
        for row in rows:
            parts = cell_lines(row)
            height = max(len(part) for part in parts)
            for index in range(height):
                values = [part[index] if index < len(part) else "" for part in parts]
                lines.append(render(values, column_styles))
        lines.append(box["bl"] + box["h"] * inner + box["br"])
        return lines

    def print_table(self, *args, **kwargs) -> None:
        for line in self.table(*args, **kwargs):
            print(line)
