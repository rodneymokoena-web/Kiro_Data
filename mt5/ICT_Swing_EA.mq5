//+------------------------------------------------------------------+
//|                                              ICT_Swing_EA.mq5     |
//|   ICT swing model (US100): D/W/M/4H sweep -> 4H FVG inverted on   |
//|   1H -> limit at the 4H IFVG -> stop above the 1H order block,    |
//|   target the 1H swing low. Mirrors the TradingView / Python rules.|
//|                                                                   |
//|   SHORT described; LONG is the mirror image. Uses only COMPLETED  |
//|   candles (no repaint). US100 only by default.                    |
//|                                                                   |
//|   NOTE: compile and test in MetaEditor / Strategy Tester before   |
//|   any live use. Backtests showed ~20-25R over 2021-2026 at 1%     |
//|   risk, ~6-8% max drawdown - results on your broker will differ.  |
//+------------------------------------------------------------------+
#property copyright "ICT Swing EA"
#property version   "1.30"
#property strict

#include <Trade/Trade.mqh>

//------------------------------------------------------------------ inputs
input group "Mode"
input bool   InpLiveTrading   = true;    // true = fully automatic (places/cancels/manages orders); false = alerts only
input double InpRiskPct       = 1.0;     // risk per trade (% of account balance)
input bool   InpUS100Only     = true;    // trade only on a US100 / NAS100 / USTEC chart

input group "Automation safety"
input bool   InpAllowRealAccount = false; // orders on a REAL account are blocked unless this is true (demo/prop-eval accounts are fine)
input bool   InpOneTradeAtATime  = true;  // never hold more than one swing order/position
input double InpMaxSpread        = 8.0;   // skip placing orders while spread > this (price units; 0 = off)
input double InpDailyLossPct     = 4.0;   // stop trading for the day if equity falls this % from the day's start (0 = off)
input double InpMaxDrawdownPct   = 8.0;   // stop trading if equity falls this % from its peak (0 = off). Stays halted until reset
input bool   InpFlattenOnLimit   = false; // also close open positions when a loss limit is hit
input bool   InpResetPeak        = false; // set true for one start to reset the stored equity peak (then set back to false)

input group "Rule 1 - liquidity (swing sizes, candles each side)"
input int    InpPivDWM        = 2;       // D/W/M swing size
input int    InpPiv4H         = 10;      // 4H swing size (10 = major swings; 2 = all; 0 = off)
input bool   InpFvgLiquidity  = true;    // also treat the FAR edge of every FRESH 4H FVG as liquidity (bearish FVG top / bullish FVG bottom)

input group "Rule 2-3 - sweep & inversion"
input bool   InpCloseBackSweep= true;    // sweep must close back through the level (rejection)
input int    InpLegLookback4H = 60;      // 4H FVG at most N 4H candles before the sweep
input int    InpInvWindow1H   = 80;      // inversion within N 1H candles of the sweep
input double InpDispATR       = 1.0;     // 1H displacement >= this * ATR(14)
input int    InpMssPivot      = 2;       // 1H MSS swing size

input group "Rule 4-7 - entry / risk"
input int    InpRetestHours   = 48;      // retest the 4H IFVG within N hours of the signal
input int    InpValidHours    = 48;      // limit order valid for N hours after the signal
input double InpStopBuffer    = 2.0;     // stop buffer in points beyond the 1H OB / sweep extreme
input double InpBE_at_R       = 1.0;     // move stop to breakeven at +R (0 = off)
input bool   InpTrailStructure= true;    // after breakeven, trail the stop to each new confirmed 1H swing formed after the fill
input double InpFixedR        = 3.0;     // target if "1H swing low" not found (fallback)
input bool   InpUseSwingLowTgt= true;    // target = 1H swing low where the leg started (else FixedR)
input ulong  InpMagic         = 770001;  // magic number

//------------------------------------------------------------------ globals
CTrade   trade;
datetime g_last1H   = 0;      // last processed 1H bar time
string   g_sym;
double   g_point;

// one pending swing setup (the model fires rarely; track the most recent live one)
struct Setup
  {
   bool     active;
   bool     isShort;
   double   fvgTop, fvgBot;    // 4H IFVG
   double   sweepExtreme;      // invalidation level
   double   entry, stop, target;
   datetime signalTime;
   datetime expiry;
   bool     ordered;
  };
Setup g_setup;

int      g_dayKey     = 0;       // yyyymmdd of the current server day
double   g_dayStartEq = 0;       // equity at the start of the day
double   g_peakEq     = 0;       // highest equity seen (persisted)
bool     g_haltedDay  = false;
bool     g_haltedDD   = false;
string   g_gvPeak, g_gvDayKey, g_gvDayEq;

// a swept level waiting for the 4H FVG inversion (the tested model watches up to InpInvWindow1H candles after the sweep)
struct Sweep
  {
   bool     isShort;
   double   level;
   double   extreme;      // running extreme since the sweep (high for a short, low for a long)
   datetime time;         // 1H open time of the sweep candle
   int      age;          // 1H candles since the sweep
  };
Sweep g_sweeps[];

//+------------------------------------------------------------------+
int OnInit()
  {
   g_sym   = _Symbol;
   g_point = _Point;
   trade.SetExpertMagicNumber(InpMagic);
   if(InpUS100Only && !IsUS100())
     {
      Print("Not a US100 chart - EA idle. Symbol: ", g_sym);
     }
   g_setup.active = false;

   long login = AccountInfoInteger(ACCOUNT_LOGIN);
   g_gvPeak   = "ICTSWING_PEAK_"   + IntegerToString((int)login);
   g_gvDayKey = "ICTSWING_DAYKEY_" + IntegerToString((int)login);
   g_gvDayEq  = "ICTSWING_DAYEQ_"  + IntegerToString((int)login);
   double eq  = AccountInfoDouble(ACCOUNT_EQUITY);
   if(InpResetPeak) GlobalVariableDel(g_gvPeak);
   g_peakEq = GlobalVariableCheck(g_gvPeak) ? GlobalVariableGet(g_gvPeak) : eq;
   if(eq > g_peakEq) g_peakEq = eq;
   GlobalVariableSet(g_gvPeak, g_peakEq);
   if(GlobalVariableCheck(g_gvDayKey) && GlobalVariableCheck(g_gvDayEq))
     { g_dayKey = (int)GlobalVariableGet(g_gvDayKey); g_dayStartEq = GlobalVariableGet(g_gvDayEq); }

   if(InpLiveTrading && !InpAllowRealAccount &&
      AccountInfoInteger(ACCOUNT_TRADE_MODE) == ACCOUNT_TRADE_MODE_REAL)
     {
      Print("REAL account detected and InpAllowRealAccount=false -> running in SIGNALS-ONLY mode. ",
            "Set InpAllowRealAccount=true to allow live orders.");
     }

   // recover state after a restart: an existing order/position of ours means a setup is already in progress
   if(HasOpenOrPending())
     {
      g_setup.active  = true;
      g_setup.ordered = true;
      g_setup.expiry  = TimeCurrent() + InpValidHours*3600;
      g_setup.sweepExtreme = 0;
      Print("Recovered an existing order/position (magic ", InpMagic, ") - managing it.");
     }
   Print("ICT Swing EA started. Mode: ", LiveAllowed() ? "AUTOMATIC" : "SIGNALS ONLY",
         " | risk ", DoubleToString(InpRiskPct,2), "% | equity peak ", DoubleToString(g_peakEq,2));
   return(INIT_SUCCEEDED);
  }

//--- orders are only placed when live trading is on and (account is not real OR real is explicitly allowed)
bool LiveAllowed()
  {
   if(!InpLiveTrading) return false;
   if(AccountInfoInteger(ACCOUNT_TRADE_MODE) == ACCOUNT_TRADE_MODE_REAL && !InpAllowRealAccount) return false;
   return true;
  }

void OnDeinit(const int reason) {}

//+------------------------------------------------------------------+
bool IsUS100()
  {
   string s = g_sym; StringToUpper(s);
   string k[] = {"NAS100","US100","USTEC","NDX","USTECH","NQ","US TECH"};
   for(int i=0;i<ArraySize(k);i++) if(StringFind(s,k[i])>=0) return true;
   return false;
  }

//+------------------------------------------------------------------+
//| run once per new completed 1H candle                              |
//+------------------------------------------------------------------+
void OnTick()
  {
   if(InpUS100Only && !IsUS100()) return;

   bool halted = RiskHalted();              // daily-loss / drawdown limits
   if(halted) HandleHalt();

   ManageOpen();                            // breakeven on open positions (every tick)
   SyncSetup();                             // clear the setup once its order/position is gone

   datetime t1[2];
   if(CopyTime(g_sym, PERIOD_H1, 0, 2, t1) < 2) return;
   datetime closed1H = t1[1];               // the just-closed 1H candle's open time
   if(closed1H == g_last1H) return;         // only act on a newly completed 1H candle
   g_last1H = closed1H;

   ManageTrail();                           // structure trail on open positions (new 1H candle)

   if(g_setup.active) UpdateSetup();        // cancel / expire / retry a pending setup

   if(!g_setup.active && !halted && !(InpOneTradeAtATime && HasOpenOrPending()))
      ScanForSetup();
  }

//--- our own position / pending order on this symbol
bool HasPosition()
  {
   for(int i=PositionsTotal()-1;i>=0;i--)
     {
      ulong tk = PositionGetTicket(i);
      if(tk==0) continue;
      if(PositionGetInteger(POSITION_MAGIC)==(long)InpMagic && PositionGetString(POSITION_SYMBOL)==g_sym) return true;
     }
   return false;
  }
bool HasPending()
  {
   for(int i=OrdersTotal()-1;i>=0;i--)
     {
      ulong tk = OrderGetTicket(i);
      if(tk==0) continue;
      if(OrderGetInteger(ORDER_MAGIC)==(long)InpMagic && OrderGetString(ORDER_SYMBOL)==g_sym) return true;
     }
   return false;
  }
bool HasOpenOrPending() { return HasPosition() || HasPending(); }

void SyncSetup()
  {
   if(g_setup.active && g_setup.ordered && !HasOpenOrPending())
     {
      g_setup.active = false;
      Print("Setup finished (order gone / position closed).");
     }
  }

//+------------------------------------------------------------------+
//| loss limits. Daily limit resets each server day; the drawdown     |
//| limit stays on until you reset the peak (InpResetPeak).           |
//+------------------------------------------------------------------+
bool RiskHalted()
  {
   double eq = AccountInfoDouble(ACCOUNT_EQUITY);
   MqlDateTime d; TimeToStruct(TimeCurrent(), d);
   int key = d.year*10000 + d.mon*100 + d.day;
   if(key != g_dayKey || g_dayStartEq <= 0)
     {
      g_dayKey = key; g_dayStartEq = eq; g_haltedDay = false;
      GlobalVariableSet(g_gvDayKey, key); GlobalVariableSet(g_gvDayEq, eq);
     }
   if(eq > g_peakEq) { g_peakEq = eq; GlobalVariableSet(g_gvPeak, g_peakEq); }

   if(InpDailyLossPct > 0 && !g_haltedDay && eq <= g_dayStartEq*(1.0 - InpDailyLossPct/100.0))
     { g_haltedDay = true; Print("DAILY LOSS LIMIT hit (", DoubleToString(InpDailyLossPct,1), "%) - no new trades today."); }
   if(InpMaxDrawdownPct > 0 && !g_haltedDD && eq <= g_peakEq*(1.0 - InpMaxDrawdownPct/100.0))
     { g_haltedDD = true; Print("MAX DRAWDOWN LIMIT hit (", DoubleToString(InpMaxDrawdownPct,1),
                               "%) - EA halted. Set InpResetPeak=true for one restart to resume."); }
   return g_haltedDay || g_haltedDD;
  }

void HandleHalt()
  {
   if(HasPending()) CancelPending();
   if(g_setup.active && !HasPosition()) g_setup.active = false;
   if(InpFlattenOnLimit)
      for(int i=PositionsTotal()-1;i>=0;i--)
        {
         ulong tk = PositionGetTicket(i);
         if(tk==0) continue;
         if(PositionGetInteger(POSITION_MAGIC)==(long)InpMagic && PositionGetString(POSITION_SYMBOL)==g_sym) trade.PositionClose(tk);
        }
  }

//+------------------------------------------------------------------+
//| helpers: rates access                                            |
//+------------------------------------------------------------------+
int GetRates(ENUM_TIMEFRAMES tf, int count, MqlRates &r[])
  {
   ArraySetAsSeries(r, true);
   return CopyRates(g_sym, tf, 0, count, r);   // index 0 = current (forming) candle
  }

double ATR14(ENUM_TIMEFRAMES tf, int shift)
  {
   MqlRates r[];
   if(GetRates(tf, shift+16, r) < shift+16) return 0;
   double s=0; int n=14;
   for(int i=shift; i<shift+n; i++)
     {
      double hl = r[i].high - r[i].low;
      double hc = MathAbs(r[i].high - r[i+1].close);
      double lc = MathAbs(r[i].low  - r[i+1].close);
      s += MathMax(hl, MathMax(hc, lc));
     }
   return s/n;
  }

void AppendIf(double &a[], double v)
  {
   for(int i=0;i<ArraySize(a);i++) if(MathAbs(a[i]-v) < 1e-6) return;
   int n=ArraySize(a); ArrayResize(a,n+1); a[n]=v;
  }

//+------------------------------------------------------------------+
//| unbroken D/W/M/4H swing levels (confirmed pivots, not yet broken) |
//| fills arrays of highs and lows; uses completed candles only.      |
//+------------------------------------------------------------------+
void CollectSwings(ENUM_TIMEFRAMES tf, int piv, double &highs[], double &lows[])
  {
   if(piv <= 0) return;
   MqlRates r[];
   int need = 300 + 2*piv;
   int got = GetRates(tf, need, r);
   if(got < 2*piv+2) return;
   // r[0] is forming; use confirmed candles from index 1. A pivot at i needs piv candles each side (i-piv..i+piv),
   // all with larger index = older. Pivot confirmed once i-piv >= 1 (piv newer candles exist).
   for(int i=got-piv-1; i>=1+piv; i--)
     {
      bool isHigh=true, isLow=true;
      for(int k=1;k<=piv;k++)
        {
         if(r[i+k].high >= r[i].high || r[i-k].high >  r[i].high) isHigh=false;
         if(r[i+k].low  <= r[i].low  || r[i-k].low  <  r[i].low ) isLow=false;
        }
      if(isHigh)
        {
         // keep only if not yet traded above by a later (newer, lower-index) candle
         bool broken=false;
         for(int j=i-1;j>=0;j--) if(r[j].high > r[i].high){broken=true;break;}
         if(!broken) AppendIf(highs, r[i].high);
        }
      if(isLow)
        {
         bool broken=false;
         for(int j=i-1;j>=0;j--) if(r[j].low < r[i].low){broken=true;break;}
         if(!broken) AppendIf(lows, r[i].low);
        }
     }
  }


//+------------------------------------------------------------------+
//| gather all unbroken liquidity levels (highs and lows)             |
//+------------------------------------------------------------------+
//+------------------------------------------------------------------+
//| 4H FVG far-edge liquidity. A 4H FVG (3 candles, gap between      |
//| candle 1 and candle 3) is a level at its FAR edge: bearish FVG   |
//| -> its TOP (buy-side), bullish FVG -> its BOTTOM (sell-side).    |
//| FRESH only: valid while no 4H candle that CLOSED by time tj has  |
//| traded into the gap, so the 4H candle that first enters it can   |
//| still be swept. tj = open time of the 1H candle being scanned.   |
//+------------------------------------------------------------------+
void CollectFvgEdges(datetime tj, double &highs[], double &lows[])
  {
   MqlRates r[];
   int got = GetRates(PERIOD_H4, 320, r);
   if(got < 5) return;
   int sec = PeriodSeconds(PERIOD_H4);
   for(int i=got-3; i>=0; i--)                  // i = candle 3 (index 0 = newest/forming)
     {
      if(r[i].time + sec > tj) continue;        // candle 3 not yet closed when the 1H candle opened
      bool bear = r[i].high < r[i+2].low;
      bool bull = r[i].low  > r[i+2].high;
      if(!bear && !bull) continue;
      double nearEdge = bear ? r[i].high : r[i].low;       // edge price trades through first
      bool touched = false;
      for(int k=i-1; k>=0; k--)                 // newer candles that were already closed at tj
        {
         if(r[k].time + sec > tj) continue;
         if(bear ? r[k].high >= nearEdge : r[k].low <= nearEdge) { touched=true; break; }
        }
      if(touched) continue;
      if(bear) AppendIf(highs, r[i+2].low);
      else     AppendIf(lows,  r[i+2].high);
     }
  }

void LiquidityLevels(datetime tj, double &highs[], double &lows[])
  {
   ArrayResize(highs,0); ArrayResize(lows,0);
   CollectSwings(PERIOD_MN1, InpPivDWM, highs, lows);
   CollectSwings(PERIOD_W1,  InpPivDWM, highs, lows);
   CollectSwings(PERIOD_D1,  InpPivDWM, highs, lows);
   if(InpPiv4H>0) CollectSwings(PERIOD_H4, InpPiv4H, highs, lows);
   if(InpFvgLiquidity) CollectFvgEdges(tj, highs, lows);
  }

//+------------------------------------------------------------------+
//| SCAN (each completed 1H candle):                                  |
//|  1) register a new SWEEP if this candle took a liquidity level    |
//|     (close-back rejection if enabled), remembering its extreme    |
//|  2) age/extend every live sweep; drop those older than the window |
//|  3) for each live sweep test the 4H-FVG inversion + displacement  |
//|     + MSS on this candle; the first that passes becomes the setup |
//+------------------------------------------------------------------+
void ScanForSetup()
  {
   MqlRates h1[];
   if(GetRates(PERIOD_H1, InpInvWindow1H+20, h1) < 5) return;
   int j = 1;                                   // the just-closed 1H candle
   double hi = h1[j].high, lo = h1[j].low, cl = h1[j].close;

   // 1) new sweeps on this candle
   double highs[], lows[];
   LiquidityLevels(h1[j].time, highs, lows);
   for(int i=0;i<ArraySize(highs);i++)
     {
      double lvl = highs[i];
      if(hi > lvl && (!InpCloseBackSweep || cl < lvl)) AddSweep(true, lvl, hi, h1[j].time);
     }
   for(int i=0;i<ArraySize(lows);i++)
     {
      double lvl = lows[i];
      if(lo < lvl && (!InpCloseBackSweep || cl > lvl)) AddSweep(false, lvl, lo, h1[j].time);
     }

   // 2)+3) age sweeps, extend their extreme, and test inversion
   for(int s=ArraySize(g_sweeps)-1; s>=0; s--)
     {
      if(g_sweeps[s].time != h1[j].time) g_sweeps[s].age++;          // not the sweep candle itself
      if(g_sweeps[s].isShort) g_sweeps[s].extreme = MathMax(g_sweeps[s].extreme, hi);
      else                    g_sweeps[s].extreme = MathMin(g_sweeps[s].extreme, lo);
      if(g_sweeps[s].age > InpInvWindow1H) { RemoveSweep(s); continue; }

      bool ok = g_sweeps[s].isShort ? TryBuildShort(g_sweeps[s].level, g_sweeps[s].extreme, j)
                                    : TryBuildLong (g_sweeps[s].level, g_sweeps[s].extreme, j);
      if(ok) { RemoveSweep(s); return; }       // one setup at a time
     }
  }

void AddSweep(bool isShort, double level, double extreme, datetime t)
  {
   for(int i=0;i<ArraySize(g_sweeps);i++)                 // do not register the same level twice
      if(g_sweeps[i].isShort==isShort && MathAbs(g_sweeps[i].level-level)<1e-6) return;
   int n=ArraySize(g_sweeps); ArrayResize(g_sweeps,n+1);
   g_sweeps[n].isShort=isShort; g_sweeps[n].level=level; g_sweeps[n].extreme=extreme; g_sweeps[n].time=t; g_sweeps[n].age=0;
  }

void RemoveSweep(int idx)
  {
   int n=ArraySize(g_sweeps);
   for(int i=idx;i<n-1;i++) g_sweeps[i]=g_sweeps[i+1];
   ArrayResize(g_sweeps,n-1);
  }

//+------------------------------------------------------------------+
//| find the last bullish 4H FVG of the sweeping leg, intact at the   |
//| sweep, inverted by this 1H close; require 1H displacement + MSS.  |
//| (LONG mirrored in TryBuildLong)                                   |
//+------------------------------------------------------------------+
bool TryBuildShort(double sweptLevel, double sweepExt, int j1)
  {
   MqlRates h4[]; if(GetRates(PERIOD_H4, InpLegLookback4H+10, h4) < 6) return false;
   MqlRates h1[]; if(GetRates(PERIOD_H1, 200, h1) < 10) return false;

   // last bullish 4H FVG (gap up): low[i] > high[i+2], scanning newest->older within the lookback
   double fvgBot=0, fvgTop=0; bool found=false;
   for(int i=1; i<InpLegLookback4H && i+2<ArraySize(h4); i++)
     {
      if(h4[i].low > h4[i+2].high)              // bullish FVG; zone = [high(i+2) .. low(i)]
        {
         double bot = h4[i+2].high, top = h4[i].low;
         // intact: no 4H close below bot before now (candles i-1..1, newer)
         bool intact=true;
         for(int k=i-1;k>=1;k--) if(h4[k].close < bot){intact=false;break;}
         if(intact){ fvgBot=bot; fvgTop=top; found=true; break; }
        }
     }
   if(!found) return false;

   // this 1H close must be below the FVG bottom (the inversion)
   if(h1[j1].close >= fvgBot) return false;

   // 1H displacement: run of consecutive bearish closes ending at j1, moving >= ATR
   double atr = ATR14(PERIOD_H1, j1);
   int run=0; double runOpen=h1[j1].open;
   for(int k=j1;k<ArraySize(h1);k++){ if(h1[k].close < h1[k].open){run++; runOpen=h1[k].open;} else break; }
   double move = runOpen - h1[j1].close;
   if(run < 1 || move < InpDispATR*atr) return false;

   // 1H MSS: close below the last confirmed 1H swing low before the sweep extreme
   if(!MSS_Short(h1, j1)) return false;

   RegisterSetup(true, fvgTop, fvgBot, sweepExt, h1[j1].time);
   return true;
  }

bool TryBuildLong(double sweptLevel, double sweepExt, int j1)
  {
   MqlRates h4[]; if(GetRates(PERIOD_H4, InpLegLookback4H+10, h4) < 6) return false;
   MqlRates h1[]; if(GetRates(PERIOD_H1, 200, h1) < 10) return false;
   double fvgBot=0, fvgTop=0; bool found=false;
   for(int i=1; i<InpLegLookback4H && i+2<ArraySize(h4); i++)
     {
      if(h4[i].high < h4[i+2].low)              // bearish FVG; zone = [high(i) .. low(i+2)]
        {
         double bot = h4[i].high, top = h4[i+2].low;
         bool intact=true;
         for(int k=i-1;k>=1;k--) if(h4[k].close > top){intact=false;break;}
         if(intact){ fvgBot=bot; fvgTop=top; found=true; break; }
        }
     }
   if(!found) return false;
   if(h1[j1].close <= fvgTop) return false;
   double atr = ATR14(PERIOD_H1, j1);
   int run=0; double runOpen=h1[j1].open;
   for(int k=j1;k<ArraySize(h1);k++){ if(h1[k].close > h1[k].open){run++; runOpen=h1[k].open;} else break; }
   double move = h1[j1].close - runOpen;
   if(run < 1 || move < InpDispATR*atr) return false;
   if(!MSS_Long(h1, j1)) return false;
   RegisterSetup(false, fvgTop, fvgBot, sweepExt, h1[j1].time);
   return true;
  }

//+------------------------------------------------------------------+
//| 1H MSS: a close through the last confirmed 1H swing (opposite)    |
//+------------------------------------------------------------------+
bool MSS_Short(MqlRates &h1[], int j1)
  {
   int p=InpMssPivot;
   for(int i=j1+p; i+p<ArraySize(h1); i++)
     {
      bool piv=true;
      for(int k=1;k<=p;k++) if(h1[i+k].low <= h1[i].low || h1[i-k].low < h1[i].low) piv=false;
      if(piv) { for(int k=j1;k<=i-p;k++) if(h1[k].close < h1[i].low) return true; return false; }
     }
   return false;
  }
bool MSS_Long(MqlRates &h1[], int j1)
  {
   int p=InpMssPivot;
   for(int i=j1+p; i+p<ArraySize(h1); i++)
     {
      bool piv=true;
      for(int k=1;k<=p;k++) if(h1[i+k].high >= h1[i].high || h1[i-k].high > h1[i].high) piv=false;
      if(piv) { for(int k=j1;k<=i-p;k++) if(h1[k].close > h1[i].high) return true; return false; }
     }
   return false;
  }

//+------------------------------------------------------------------+
//| STOP: 50% of the 1H order block of the drop. OB = the last up-    |
//| close 1H candle before the first bearish 1H FVG formed after the  |
//| sweep extreme. Fallback: beyond the sweep extreme.  (short; long  |
//| mirrored)                                                         |
//+------------------------------------------------------------------+
double StopFromOB(bool isShort, double sweepExtreme, double fvgBot, double fvgTop)
  {
   MqlRates h1[]; if(GetRates(PERIOD_H1, 150, h1) < 10) return sweepExtreme;
   // find the first FVG of the drop (bearish for a short) scanning from the extreme toward now (older->newer)
   int extIdx=-1;
   for(int i=1;i<ArraySize(h1);i++)
     {
      if(isShort ? (h1[i].high >= sweepExtreme-1e-6) : (h1[i].low <= sweepExtreme+1e-6)) { extIdx=i; break; }
     }
   if(extIdx<0) return sweepExtreme;
   for(int c3 = extIdx-1; c3>=1; c3--)           // candle 3 of the FVG (newer than the extreme)
     {
      int c1 = c3+2;                              // candle 1 (older)
      if(c1 >= ArraySize(h1)) continue;
      bool fvg = isShort ? (h1[c3].high < h1[c1].low)    // bearish FVG
                         : (h1[c3].low  > h1[c1].high);  // bullish FVG
      if(!fvg) continue;
      // OB = last opposite-close candle at/before candle 1 (up-close for a short), up to 3 back
      for(int o=c1; o<=c1+3 && o<ArraySize(h1); o++)
        {
         bool opp = isShort ? (h1[o].close > h1[o].open) : (h1[o].close < h1[o].open);
         if(opp) return (h1[o].high + h1[o].low)/2.0;
        }
      break;
     }
   return sweepExtreme;
  }

//+------------------------------------------------------------------+
//| TARGET: most recent confirmed 1H swing low (short) / high (long)  |
//| before the 4H FVG's formation - approximated by the most recent   |
//| confirmed 1H swing beyond the entry.                              |
//+------------------------------------------------------------------+
double TargetSwing(bool isShort, double entry)
  {
   MqlRates h1[]; if(GetRates(PERIOD_H1, 400, h1) < 20) return 0;
   int p=2;
   for(int i=1+p; i+p<ArraySize(h1); i++)
     {
      bool piv=true;
      for(int k=1;k<=p;k++)
        {
         if(isShort){ if(h1[i+k].low <= h1[i].low || h1[i-k].low < h1[i].low) piv=false; }
         else       { if(h1[i+k].high >= h1[i].high || h1[i-k].high > h1[i].high) piv=false; }
        }
      if(!piv) continue;
      double v = isShort ? h1[i].low : h1[i].high;
      if(isShort ? v < entry : v > entry) return v;
     }
   return 0;
  }

//+------------------------------------------------------------------+
void RegisterSetup(bool isShort, double fvgTop, double fvgBot, double ext, datetime t)
  {
   g_setup.active       = true;
   g_setup.isShort      = isShort;
   g_setup.fvgTop       = fvgTop;
   g_setup.fvgBot       = fvgBot;
   g_setup.sweepExtreme = ext;
   g_setup.signalTime   = t;
   g_setup.expiry       = t + 3600 + InpValidHours*3600;   // from the close of the signal candle
   g_setup.ordered      = false;
   g_setup.entry        = isShort ? fvgBot : fvgTop;     // limit at the 4H IFVG near edge

   double base = StopFromOB(isShort, ext, fvgBot, fvgTop);
   double buf  = InpStopBuffer * g_point;
   g_setup.stop = isShort ? base + buf : base - buf;
   double risk = MathAbs(g_setup.entry - g_setup.stop);

   double tgt = InpUseSwingLowTgt ? TargetSwing(isShort, g_setup.entry) : 0;
   if(tgt==0 || (isShort ? tgt >= g_setup.entry : tgt <= g_setup.entry))
      tgt = isShort ? g_setup.entry - InpFixedR*risk : g_setup.entry + InpFixedR*risk;
   g_setup.target = tgt;

   // stop must be on the correct side of the entry
   if(isShort ? g_setup.stop <= g_setup.entry : g_setup.stop >= g_setup.entry) { g_setup.active=false; return; }

   string msg = StringFormat("%s SETUP %s | limit %.2f  SL %.2f  TP %.2f  (risk %.1f pts)",
                             isShort?"SHORT":"LONG", g_sym, g_setup.entry, g_setup.stop, g_setup.target, risk/g_point);
   Print(msg); Alert(msg); SendNotification(msg);
   if(LiveAllowed()) PlaceOrder();
  }

//+------------------------------------------------------------------+
//| position size so that (entry->stop) risks InpRiskPct of balance   |
//+------------------------------------------------------------------+
double LotsForRisk(double entry, double stop)
  {
   double riskMoney = AccountInfoDouble(ACCOUNT_BALANCE) * InpRiskPct/100.0;
   double tickVal  = SymbolInfoDouble(g_sym, SYMBOL_TRADE_TICK_VALUE);
   double tickSize = SymbolInfoDouble(g_sym, SYMBOL_TRADE_TICK_SIZE);
   double stepLot  = SymbolInfoDouble(g_sym, SYMBOL_VOLUME_STEP);
   double minLot   = SymbolInfoDouble(g_sym, SYMBOL_VOLUME_MIN);
   double maxLot   = SymbolInfoDouble(g_sym, SYMBOL_VOLUME_MAX);
   double dist = MathAbs(entry - stop);
   if(dist<=0 || tickVal<=0 || tickSize<=0) return 0;
   double perLot = (dist/tickSize)*tickVal;           // $ loss per 1.0 lot at the stop
   double lots = riskMoney / perLot;
   lots = MathFloor(lots/stepLot)*stepLot;
   if(lots < minLot)
     {
      Print("Risk budget too small for the minimum lot (", DoubleToString(minLot,2), ") - order skipped. Raise InpRiskPct or balance.");
      return 0;
     }
   return MathMin(maxLot, lots);
  }

void PlaceOrder()
  {
   if(g_setup.ordered) return;
   if(!LiveAllowed()) return;
   if(RiskHalted()) return;
   if(InpOneTradeAtATime && HasOpenOrPending()) { Print("Order skipped: a trade/order already exists."); return; }

   double bid = SymbolInfoDouble(g_sym, SYMBOL_BID), ask = SymbolInfoDouble(g_sym, SYMBOL_ASK);
   if(InpMaxSpread > 0 && (ask-bid) > InpMaxSpread)
     { Print("Spread ", DoubleToString(ask-bid,2), " > max ", DoubleToString(InpMaxSpread,2), " - will retry on the next 1H candle."); return; }

   int dg = (int)SymbolInfoInteger(g_sym, SYMBOL_DIGITS);
   double e = NormalizeDouble(g_setup.entry,  dg);
   double s = NormalizeDouble(g_setup.stop,   dg);
   double t = NormalizeDouble(g_setup.target, dg);
   double minDist = (double)SymbolInfoInteger(g_sym, SYMBOL_TRADE_STOPS_LEVEL) * g_point;

   // broker rule: a limit must sit at least StopsLevel away from the market on the correct side
   bool limitOK = g_setup.isShort ? (e >= bid + minDist) : (e <= ask - minDist);
   bool useMarket = false;
   if(!limitOK)
     {
      // price is already at/through the entry (the tested model fills on touch): enter at market if the stop is still valid
      double px = g_setup.isShort ? bid : ask;
      bool better = g_setup.isShort ? px >= e : px <= e;           // market price is at least as good as the limit price
      if(!better) { Print("Entry too close to the market for a limit order - skipped."); return; }
      e = px; useMarket = true;
     }
   // stop / target distance rules
   if(MathAbs(e - s) < minDist || MathAbs(t - e) < minDist) { Print("Stop/target closer than the broker minimum - skipped."); return; }
   if(g_setup.isShort ? (s <= e) : (s >= e))                  { Print("Stop on the wrong side after adjusting - skipped.");     return; }

   double lots = LotsForRisk(e, s);
   if(lots <= 0) return;

   // margin check
   double margin = 0;
   if(OrderCalcMargin(g_setup.isShort ? ORDER_TYPE_SELL : ORDER_TYPE_BUY, g_sym, lots, e, margin) &&
      margin > AccountInfoDouble(ACCOUNT_MARGIN_FREE)*0.9)
     { Print("Not enough free margin for ", DoubleToString(lots,2), " lots - skipped."); return; }

   bool ok;
   if(useMarket)
      ok = g_setup.isShort ? trade.Sell(lots, g_sym, 0, s, t, "ICT swing") : trade.Buy(lots, g_sym, 0, s, t, "ICT swing");
   else
     {
      ok = g_setup.isShort
           ? trade.SellLimit(lots, e, g_sym, s, t, ORDER_TIME_SPECIFIED, g_setup.expiry, "ICT swing")
           : trade.BuyLimit (lots, e, g_sym, s, t, ORDER_TIME_SPECIFIED, g_setup.expiry, "ICT swing");
      if(!ok && trade.ResultRetcode()==TRADE_RETCODE_INVALID_EXPIRATION)      // broker rejects expiry: use GTC, EA cancels it itself
         ok = g_setup.isShort
              ? trade.SellLimit(lots, e, g_sym, s, t, ORDER_TIME_GTC, 0, "ICT swing")
              : trade.BuyLimit (lots, e, g_sym, s, t, ORDER_TIME_GTC, 0, "ICT swing");
     }
   if(ok) { g_setup.ordered = true; Print("Order placed: ", useMarket ? "MARKET " : "LIMIT ", DoubleToString(lots,2), " lots @ ", DoubleToString(e,dg),
                                          " SL ", DoubleToString(s,dg), " TP ", DoubleToString(t,dg)); }
   else   Print("Order failed (will retry next 1H candle): ", trade.ResultRetcode(), " ", trade.ResultRetcodeDescription());
  }

//+------------------------------------------------------------------+
//| each new 1H close: cancel a setup if price opened beyond the      |
//| sweep extreme before fill, or if the retest window has expired    |
//+------------------------------------------------------------------+
void UpdateSetup()
  {
   MqlRates h1[]; if(GetRates(PERIOD_H1, 3, h1) < 2) return;
   double o1 = h1[1].open;
   // a setup recovered after a restart has no stored sweep extreme (0): skip the "beyond the extreme" cancel for it
   bool beyond = g_setup.sweepExtreme > 0 &&
                 (g_setup.isShort ? o1 > g_setup.sweepExtreme : o1 < g_setup.sweepExtreme);
   bool expired = TimeCurrent() > g_setup.expiry;
   if(beyond || expired)
     {
      if(HasPending()) CancelPending();
      if(!HasPosition()) g_setup.active = false;           // keep tracking while a position is open (it is managed by SL/TP/BE)
      return;
     }
   // still valid but the order was not placed yet (wide spread, margin, transient error): try again
   if(!g_setup.ordered && LiveAllowed()) PlaceOrder();
  }

void CancelPending()
  {
   for(int i=OrdersTotal()-1;i>=0;i--)
     {
      ulong tk = OrderGetTicket(i);
      if(tk==0) continue;
      if(OrderGetInteger(ORDER_MAGIC)==(long)InpMagic && OrderGetString(ORDER_SYMBOL)==g_sym) trade.OrderDelete(tk);
     }
  }

//+------------------------------------------------------------------+
//| structure trail (swing model): once the stop is at breakeven or   |
//| better, follow the newest CONFIRMED 1H swing high (short) / low   |
//| (long) that formed after the position opened - 2 candles each     |
//| side - and only ever tighten the stop.                            |
//+------------------------------------------------------------------+
void ManageTrail()
  {
   if(!InpTrailStructure) return;
   MqlRates h1[]; if(GetRates(PERIOD_H1, 60, h1) < 8) return;     // index 1 = last completed candle
   const int p = 2;
   for(int n=PositionsTotal()-1;n>=0;n--)
     {
      ulong tk = PositionGetTicket(n);
      if(!PositionSelectByTicket(tk)) continue;
      if(PositionGetInteger(POSITION_MAGIC)!=(long)InpMagic || PositionGetString(POSITION_SYMBOL)!=g_sym) continue;
      bool   isBuy = PositionGetInteger(POSITION_TYPE)==POSITION_TYPE_BUY;
      double open  = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl    = PositionGetDouble(POSITION_SL);
      double tp    = PositionGetDouble(POSITION_TP);
      datetime ot  = (datetime)PositionGetInteger(POSITION_TIME);
      bool atBE = isBuy ? sl >= open - 1e-6 : sl <= open + 1e-6;       // trail only once at breakeven or better
      if(!atBE) continue;
      double buf = InpStopBuffer * g_point;
      // newest confirmed swing: candle i needs p NEWER candles (i-1, i-2) and p OLDER candles (i+1, i+2)
      for(int i=1+p; i+p<ArraySize(h1); i++)
        {
         if(h1[i].time <= ot) break;                                    // only swings formed after the fill
         bool piv = true;
         for(int k=1;k<=p;k++)
           {
            if(isBuy) { if(h1[i+k].low <= h1[i].low || h1[i-k].low < h1[i].low)    piv=false; }
            else      { if(h1[i+k].high >= h1[i].high || h1[i-k].high > h1[i].high) piv=false; }
           }
         if(!piv) continue;
         double cand = isBuy ? h1[i].low - buf : h1[i].high + buf;
         bool tighter = isBuy ? cand > sl : cand < sl;
         double px = isBuy ? SymbolInfoDouble(g_sym,SYMBOL_BID) : SymbolInfoDouble(g_sym,SYMBOL_ASK);
         double minDist = (double)SymbolInfoInteger(g_sym, SYMBOL_TRADE_STOPS_LEVEL) * g_point;
         bool valid = isBuy ? cand < px - minDist : cand > px + minDist;   // stop must stay beyond the market by the broker minimum
         if(tighter && valid)
           {
            int dg = (int)SymbolInfoInteger(g_sym, SYMBOL_DIGITS);
            if(trade.PositionModify(tk, NormalizeDouble(cand,dg), tp))
               Print("Trail: stop moved to ", DoubleToString(cand,dg));
           }
         break;                                                          // only the newest swing matters
        }
     }
  }

//+------------------------------------------------------------------+
//| breakeven at +R on open positions                                 |
//+------------------------------------------------------------------+
void ManageOpen()
  {
   if(InpBE_at_R<=0) return;
   for(int i=PositionsTotal()-1;i>=0;i--)
     {
      ulong tk = PositionGetTicket(i);
      if(!PositionSelectByTicket(tk)) continue;
      if(PositionGetInteger(POSITION_MAGIC)!=(long)InpMagic || PositionGetString(POSITION_SYMBOL)!=g_sym) continue;
      bool isBuy = PositionGetInteger(POSITION_TYPE)==POSITION_TYPE_BUY;
      double open = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl   = PositionGetDouble(POSITION_SL);
      double tp   = PositionGetDouble(POSITION_TP);
      double risk = MathAbs(open - sl);
      if(risk<=0) continue;
      double px = isBuy ? SymbolInfoDouble(g_sym,SYMBOL_BID) : SymbolInfoDouble(g_sym,SYMBOL_ASK);
      bool already = isBuy ? sl >= open - 1e-6 : sl <= open + 1e-6;
      if(already) continue;
      bool reached = isBuy ? px >= open + InpBE_at_R*risk : px <= open - InpBE_at_R*risk;
      if(reached) trade.PositionModify(tk, open, tp);
     }
  }
//+------------------------------------------------------------------+
