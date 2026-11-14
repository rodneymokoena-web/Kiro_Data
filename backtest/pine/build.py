"""Build the TradingView scripts from core.pine and syntax-check them.

Usage (from the backtest folder):
    .venv/bin/python pine/build.py

Six scripts are built - one model each, as an indicator and as a strategy:
    ict_swing_indicator.pine      ict_swing_strategy.pine
    ict_intraday_indicator.pine   ict_intraday_strategy.pine
    ict_erl_irl_indicator.pine    ict_erl_irl_strategy.pine   (intraday rules + ERL / IRL: sweep ERL -> target IRL -> runner ERL)

core.pine markers:
    //#I <code>   -> line only in the indicators
    //#S <code>   -> line only in the strategies
    //#W <code>   -> line only in the swing scripts
    //#N <code>   -> line in the intraday AND the ERL/IRL scripts (ERL/IRL = the intraday model plus its own changes)
    //#X <code>   -> line only in the intraday scripts (not ERL/IRL)
    //#E <code>   -> line only in the ERL/IRL scripts
    //#{W ... //#}  -> block only in the swing scripts
    //#{N ... //#}  -> block in the intraday and the ERL/IRL scripts
    //#{X ... //#}  -> block only in the intraday scripts
    //#{E ... //#}  -> block only in the ERL/IRL scripts
Everything else is shared, so both models keep identical common logic.
"""
from pathlib import Path

from pynescript.ast import parse

HERE = Path(__file__).parent
# file name -> (I = indicator / S = strategy, W = swing / N = intraday / E = ERL-IRL intraday)
TARGETS = {
    "ict_swing_indicator.pine": ("I", "W"),
    "ict_swing_strategy.pine": ("S", "W"),
    "ict_intraday_indicator.pine": ("I", "N"),
    "ict_intraday_strategy.pine": ("S", "N"),
    "ict_erl_irl_indicator.pine": ("I", "E"),
    "ict_erl_irl_strategy.pine": ("S", "E"),
}
TITLES = {
    ("I", "W"): ('indicator("ICT Swing - sweep > 4H IFVG (US100)", shorttitle="ICT Swing"', "Swing indicator"),
    ("S", "W"): ('strategy("ICT Swing Strategy - sweep > 4H IFVG (US100)", shorttitle="ICT Swing Strategy"', "Swing strategy"),
    ("I", "N"): ('indicator("ICT Intraday - 5m sweep > 5m IFVG (US100)", shorttitle="ICT Intraday"', "Intraday indicator"),
    ("S", "N"): ('strategy("ICT Intraday Strategy - 5m sweep > 5m IFVG (US100)", shorttitle="ICT Intraday Strategy"', "Intraday strategy"),
    ("I", "E"): ('indicator("ICT ERL/IRL - sweep ERL > 5m IFVG > draw to IRL (US100)", shorttitle="ICT ERL/IRL"', "ERL/IRL indicator"),
    ("S", "E"): ('strategy("ICT ERL/IRL Strategy - sweep ERL > 5m IFVG > draw to IRL (US100)", shorttitle="ICT ERL/IRL Strategy"', "ERL/IRL strategy"),
}


def included(letter: str, model: str) -> bool:
    """Is a //#<letter> line / block part of this model? N = intraday incl. ERL/IRL, X = intraday only."""
    return letter == model or (letter == "N" and model == "E") or (letter == "X" and model == "N")
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
            depth, skip = 1, not included(line[4], model)
            continue
        if line.startswith("//#}"):
            depth, skip = 0, False
            continue
        if skip:
            continue
        if line[:5] in ("//#I ", "//#S ", "//#W ", "//#N ", "//#X ", "//#E "):
            if line[3] == kind or included(line[3], model):
                out.append(line[5:])
            continue
        out.append(line)
    if depth:
        raise ValueError("unclosed //#{ block")
    text = "\n".join(out) + "\n"
    title, label = TITLES[(kind, model)]
    text = text.replace(OLD_TITLE[kind], title)
    return text.replace("//  Generated from pine/core.pine by pine/build.py",
                        f"//  {label} - generated from pine/core.pine by pine/build.py")


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
