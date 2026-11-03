"""How many US100 setups survive each rule (setup funnel).

Usage:
    DATA_SOURCE=pepperstone_oos TEST_START=2021-04-01 .venv/bin/python funnel.py
"""
from collections import Counter

import numpy as np
import pandas as pd

import ifvg
import ifvg_1h
import structure
import swings as S


def main() -> None:
    for sym, (f1, _, _) in S.SYMBOLS.items():
        h1 = S.load(S.DATA / f1)
        htf = {tf: S.build_htf(h1, tf) for tf in ("D", "W", "M", "4H")}
        h4 = htf["4H"].drop(columns=["Start", "End"])
        lv = pd.concat([S.find_swings(htf[tf], tf) for tf in ("M", "W", "D")], ignore_index=True)
        lv = S.add_break_times(lv, h4)
        lv = lv[lv.broken_time.notna() & (lv.broken_time >= max(S.TEST_START, h4.index[0])) & lv.tf.isin(ifvg.SWEEP_TFS)]
        o, h, l, c = (h4[k].to_numpy() for k in ("Open", "High", "Low", "Close"))
        n = len(h4)
        fv = ifvg.find_fvgs(h4)
        cnt = Counter()
        sweep_candles = set()
        for x in lv.itertuples(index=False):
            s = h4.index.get_indexer([x.broken_time])[0]
            sweep_candles.add((s, x.type))
            cnt["1 level swept"] += 1
            want = "bull" if x.type == "high" else "bear"
            org = ifvg.leg_origin(o, h, l, c, s, x.type == "high")
            if org < 0:
                continue
            cand = fv[(fv.dir == want) & (fv.idx - 2 >= org) & ((fv.inv_idx < 0) | (fv.inv_idx >= s))]
            if ifvg.FVG_INTO_SWEEP:
                cand = cand[cand.idx - 1 <= s]
            if cand.empty:
                continue
            cnt["2 4H FVG in leg, into sweep"] += 1
            inv = cand[(cand.inv_idx >= s) & (cand.inv_idx <= min(s + ifvg.INVERT_WINDOW, n - 1)) & (cand.inv_idx > cand.idx)]
            if inv.empty:
                continue
            cnt["3 4H FVG inverted (close) within 20 4H candles"] += 1
            ok = [structure.quality(h4, r, s, want) for _, r in inv.iterrows()]
            if any(q["disp_candles"] >= structure.DISP_MIN_CANDLES and q["disp_atr"] >= structure.DISP_MIN_ATR for q in ok):
                cnt["4a ... with displacement"] += 1
            if any(q["passed"] for q in ok):
                cnt["4b ... with displacement AND CISD/MSS"] += 1
        h4s, setups = ifvg_1h.build_4h_setups(h1)
        f1 = ifvg.find_fvgs(h1)
        st5 = Counter(ifvg_1h.find_1h_ifvg(st, h1, f1)["status"] for st in setups)
        years = (h1.index[-1] - max(S.TEST_START, h1.index[0])).days / 365.25
        print(f"\n{S.DATA_SOURCE} {sym}: {years:.1f} years, {len(sweep_candles)} distinct sweep candles")
        for k in sorted(cnt):
            print(f"   {k:<48} {cnt[k]:4d}   ({cnt[k] / years:5.1f} / year)")
        print(f"   {'5 unique 4H setups (after merging levels)':<48} {len(setups):4d}   ({len(setups) / years:5.1f} / year)")
        print(f"   {'6 1H IFVG signal (retest + 1H inversion)':<48} {st5.get('signal', 0):4d}   ({st5.get('signal', 0) / years:5.1f} / year)   lost: {dict((k, v) for k, v in st5.items() if k != 'signal')}")


if __name__ == "__main__":
    main()
