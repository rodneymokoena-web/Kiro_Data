"""4H FVG far edge as extra Rule 1 liquidity. FVG_LIQ=0|1 env. Usage: DATA_SOURCE=.. TEST_START=.. FVG_LIQ=.. python fvgliq_experiments.py"""
import contextlib, io
import pandas as pd
import backtest as B, swing_snap as SN, swings as S, ifvg
B.plot_trade = lambda *a, **k: None
with contextlib.redirect_stdout(io.StringIO()):
    sw = SN.run(); it = B.run()
it = it[(it.entry_tf == "5m") & (it.entry_mode == "touch")]
rows = [{"source": S.DATA_SOURCE, "fvg_liq": int(ifvg.FVG_LIQ), "model": m, "entry_time": r.entry_time, "exit": r.exit, "r_net": r.r_net}
        for m, d in (("swing", sw), ("intraday", it)) for r in d.itertuples(index=False)]
pd.DataFrame(rows).to_csv(f"output/fvgliq_{S.DATA_SOURCE}_{int(ifvg.FVG_LIQ)}{__import__('os').environ.get('FVG_LIQ_MODE','all') if ifvg.FVG_LIQ else ''}.csv", index=False)
print("done", S.DATA_SOURCE, ifvg.FVG_LIQ, len(sw), len(it))
