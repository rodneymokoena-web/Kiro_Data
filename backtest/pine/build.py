"""Build the TradingView scripts from core.pine and syntax-check them.

Usage (from the backtest folder):
    .venv/bin/python pine/build.py

Four scripts are built - one model each, as an indicator and as a strategy:
    ict_swing_indicator.pine      ict_swing_strategy.pine
    ict_intraday_indicator.pine   ict_intraday_strategy.pine

core.pine markers:
    //#I <code>   -> line only in the indicators
    //#S <code>   -> line only in the strategies
    //#W <code>   -> line only in the swing scripts
    //#N <code>   -> line only in the intraday scripts
    //#{W ... //#}  -> block only in the swing scripts
    //#{N ... //#}  -> block only in the intraday scripts
Everything else is shared, so both models keep identical common logic.
"""
from pathlib import Path

from pynescript.ast import parse

HERE = Path(__file__).parent
# file name -> (I = indicator / S = strategy, W = swing / N = intraday)
TARGETS = {
    "ict_swing_indicator.pine": ("I", "W"),
    "ict_swing_strategy.pine": ("S", "W"),
    "ict_intraday_indicator.pine": ("I", "N"),
    "ict_intraday_strategy.pine": ("S", "N"),
}
TITLES = {
    ("I", "W"): ('indicator("ICT Swing - sweep > 4H IFVG (US100)", shorttitle="ICT Swing"', "Swing indicator"),
    ("S", "W"): ('strategy("ICT Swing Strategy - sweep > 4H IFVG (US100)", shorttitle="ICT Swing Strategy"', "Swing strategy"),
    ("I", "N"): ('indicator("ICT Intraday - 5m sweep > 5m IFVG (US100)", shorttitle="ICT Intraday"', "Intraday indicator"),
    ("S", "N"): ('strategy("ICT Intraday Strategy - 5m sweep > 5m IFVG (US100)", shorttitle="ICT Intraday Strategy"', "Intraday strategy"),
}
OLD_TITLE = {
    "I": 'indicator("ICT Sweep > IFVG > MSS (rules 1-7)", shorttitle="ICT IFVG"',
    "S": 'strategy("ICT Sweep > IFVG > MSS Strategy (rules 1-7)", shorttitle="ICT IFVG Strategy"',
}


def build(kind: str, model: str) -> str:
    out, skip, depth = [], False, 0
    for line in (HERE / "core.pine").read_text().splitlines():
        if line.startswith("//#{"):
            if depth:
                raise ValueError("nested //#{ blocks are not supported")
            depth, skip = 1, line[4] != model
            continue
        if line.startswith("//#}"):
            depth, skip = 0, False
            continue
        if skip:
            continue
        if line[:5] in ("//#I ", "//#S ", "//#W ", "//#N "):
            if line[3] in (kind, model):
                out.append(line[5:])
            continue
        out.append(line)
    if depth:
        raise ValueError("unclosed //#{ block")
    text = "\n".join(out) + "\n"
    title, label = TITLES[(kind, model)]
    text = text.replace(OLD_TITLE[kind], title)
    return text.replace("Generated from pine/core.pine by pine/build.py",
                        f"{label} - generated from pine/core.pine by pine/build.py")


def main() -> None:
    for name, (kind, model) in TARGETS.items():
        text = build(kind, model)
        (HERE / name).write_text(text)
        try:
            parse(text)
            status = "syntax OK"
        except Exception as e:  # pynescript raises on syntax errors
            status = f"SYNTAX ERROR: {e}"
        print(f"{name:30s} {len(text.splitlines()):4d} lines  {status}")


if __name__ == "__main__":
    main()
