"""Build the TradingView indicator and strategy from core.pine and syntax-check both.

Usage (from the backtest folder):
    .venv/bin/python pine/build.py

core.pine markers:
    //#I <code>   -> line only in the indicator
    //#S <code>   -> line only in the strategy
Everything else is shared, so the two scripts always use identical logic.
"""
from pathlib import Path

from pynescript.ast import parse

HERE = Path(__file__).parent
TARGETS = {
    "ict_ifvg_indicator.pine": "I",
    "ict_ifvg_strategy.pine": "S",
}


def build(kind: str) -> str:
    out = []
    for line in (HERE / "core.pine").read_text().splitlines():
        if line.startswith("//#I ") or line.startswith("//#S "):
            if line[3] == kind:
                out.append(line[5:])
            continue
        out.append(line)
    text = "\n".join(out) + "\n"
    return text.replace("Generated from pine/core.pine by pine/build.py",
                        f"{'Indicator' if kind == 'I' else 'Strategy'} - generated from pine/core.pine by pine/build.py")


def main() -> None:
    for name, kind in TARGETS.items():
        text = build(kind)
        (HERE / name).write_text(text)
        try:
            parse(text)
            status = "syntax OK"
        except Exception as e:  # pynescript raises on syntax errors
            status = f"SYNTAX ERROR: {e}"
        print(f"{name:28s} {len(text.splitlines()):4d} lines  {status}")


if __name__ == "__main__":
    main()
