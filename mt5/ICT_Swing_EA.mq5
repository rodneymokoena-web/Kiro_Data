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
//|   any live use. Backtests showed ~60-80R over 2021-2026 at 1%     |
//|   risk per entry, ~6-12% max drawdown - results on your broker will differ.  |
//+------------------------------------------------------------------+
#property copyright "ICT Swing EA"
#property version   "1.51"
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
input int    InpLegLookback4H = 10;      // 4H FVG at most N 4H candles before the sweep
input int    InpInvWindow1H   = 80;      // inversion within N 1H candles of the sweep
input double InpDispATR       = 1.0;     // 1H displacement >= this * ATR(14)
input int    InpMssPivot      = 2;       // 1H MSS swing size

input group "Rule 4-7 - entry / risk"
input int    InpRetestHours   = 48;      // retest the 4H IFVG within N hours of the signal
input int    InpValidHours    = 48;      // limit order valid for N hours after the signal
input double InpStopBuffer    = 2.0;     // stop buffer in points beyond the 1H OB / sweep extreme
input double InpBE_at_R       = 1.0;     // move stop to breakeven at +R (0 = off)
input bool   InpBreakerEntry  = true;    // second, independent entry per setup: limit at a 1H breaker FVG (magic = InpMagic+1)
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
   datetime extTime;           // 1H open time of the sweep-extreme candle
   datetime fvgMid;            // open time of the 4H FVG's middle candle (target anchor)
   ulong    magic;             // InpMagic = 4H IFVG entry, InpMagic+1 = 1H breaker FVG entry
  };
Setup g_setup;
Setup g_setupB;                // the 1H breaker FVG entry (second, independent trade of the same setup)

// a swing setup waiting for its 1H breaker FVG
struct BrkWatch
  {
   bool     active;
   bool     isShort;
   double   fvgTop, fvgBot;    // 4H IFVG
   double   ext;               // sweep extreme
   datetime extTime, fvgMid;
   datetime sigTime;
   datetime expire;
  };
BrkWatch g_bw;

bool IsOurMagic(long m) { return m==(long)InpMagic || m==(long)(InpMagic+1); }

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
   g_setup.active = false; g_setup.magic = InpMagic;
   g_setupB.active = false; g_setupB.magic = InpMagic+1;
   g_bw.active = false;

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
   if(HasOpenOrPending(InpMagic))
     {
      g_setup.active  = true;
      g_setup.ordered = true;
      g_setup.expiry  = TimeCurrent() + InpValidHours*3600;
      g_setup.sweepExtreme = 0;
      Print("Recovered an existing order/position (magic ", InpMagic, ") - managing it.");
     }
   if(HasOpenOrPending(InpMagic+1))
     {
      g_setupB.active  = true;
      g_setupB.ordered = true;
      g_setupB.expiry  = TimeCurrent() + InpValidHours*3600;
      g_setupB.sweepExtreme = 0;
      Print("Recovered an existing breaker order/position (magic ", InpMagic+1, ") - managing it.");
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

   if(g_setup.active)  UpdateSetup(g_setup);    // cancel / expire / retry a pending setup
   if(g_setupB.active) UpdateSetup(g_setupB);
   if(InpBreakerEntry && g_bw.active && !halted) CheckBreaker();   // look for the 1H breaker FVG of the current setup

   if(!g_setup.active && !halted && !(InpOneTradeAtATime && HasOpenOrPending(InpMagic)))
      ScanForSetup();
  }

//--- our own position / pending order on this symbol
bool HasPosition(ulong magic)
  {
   for(int i=PositionsTotal()-1;i>=0;i--)
     {
      ulong tk = PositionGetTicket(i);
      if(tk==0) continue;
      if(PositionGetInteger(POSITION_MAGIC)==(long)magic && PositionGetString(POSITION_SYMBOL)==g_sym) return true;
     }
   return false;
  }
bool HasPending(ulong magic)
  {
   for(int i=OrdersTotal()-1;i>=0;i--)
     {
      ulong tk = OrderGetTicket(i);
      if(tk==0) continue;
      if(OrderGetInteger(ORDER_MAGIC)==(long)magic && OrderGetString(ORDER_SYMBOL)==g_sym) return true;
     }
   return false;
  }
bool HasOpenOrPending(ulong magic) { return HasPosition(magic) || HasPending(magic); }

void SyncSetup()
  {
   if(g_setup.active && g_setup.ordered && !HasOpenOrPending(InpMagic))
     {
      g_setup.active = false;
      Print("Setup finished (order gone / position closed).");
     }
   if(g_setupB.active && g_setupB.ordered && !HasOpenOrPending(InpMagic+1))
     {
      g_setupB.active = false;
      Print("Breaker setup finished (order gone / position closed).");
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
   if(HasPending(InpMagic))   CancelPending(InpMagic);
   if(HasPending(InpMagic+1)) CancelPending(InpMagic+1);
   if(g_setup.active  && !HasPosition(InpMagic))   g_setup.active  = false;
   if(g_setupB.active && !HasPosition(InpMagic+1)) g_setupB.active = false;
   g_bw.active = false;
   if(InpFlattenOnLimit)
      for(int i=PositionsTotal()-1;i>=0;i--)
        {
         ulong tk = PositionGetTicket(i);
         if(tk==0) continue;
         if(IsOurMagic(PositionGetInteger(POSITION_MAGIC)) && PositionGetString(POSITION_SYMBOL)==g_sym) trade.PositionClose(tk);
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

int GetChrono(ENUM_TIMEFRAMES tf, int count, MqlRates &r[])
  {
   ArraySetAsSeries(r, false);                 // oldest first; the LAST element is the forming candle
   return CopyRates(g_sym, tf, 0, count, r);
  }

double ATR14c(const MqlRates &r[], int idx)    // mean true range of the 14 candles ending at idx (chronological array)
  {
   double sum=0; int cnt=0;
   for(int i=idx; i>idx-14 && i>=1; i--)
     {
      sum += MathMax(r[i].high-r[i].low, MathMax(MathAbs(r[i].high-r[i-1].close), MathAbs(r[i].low-r[i-1].close)));
      cnt++;
     }
   return cnt>0 ? sum/cnt : 0;
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
//| 1H history used to decide whether a level was already swept       |
//| (a 1H candle that wicked through it AND closed back = consumed).   |
//+------------------------------------------------------------------+
MqlRates g_h1c[];
int      g_n1c = 0;

void LoadH1Cache()
  {
   ArraySetAsSeries(g_h1c, false);
   int want[3] = {45000, 20000, 5000};
   g_n1c = 0;
   for(int a=0;a<3;a++) { g_n1c = CopyRates(g_sym, PERIOD_H1, 0, want[a], g_h1c); if(g_n1c > 0) break; }
  }

int LowerBoundTime(datetime t)                 // first index in g_h1c with time >= t
  {
   int lo=0, hi=g_n1c;
   while(lo<hi) { int mid=(lo+hi)/2; if(g_h1c[mid].time < t) lo=mid+1; else hi=mid; }
   return lo;
  }

bool LevelAlive(double lvl, bool isHigh, datetime ct, datetime tj)
  {
   for(int k=LowerBoundTime(ct); k<g_n1c && g_h1c[k].time < tj; k++)
      if(isHigh ? (g_h1c[k].high > lvl && g_h1c[k].close < lvl) : (g_h1c[k].low < lvl && g_h1c[k].close > lvl)) return false;
   return true;
  }

//+------------------------------------------------------------------+
//| D/W/M/4H swing levels (confirmed pivots) that no 1H candle has     |
//| swept yet (wick through AND close back), as of the 1H candle that  |
//| opened at tj. Uses completed candles only.                         |
//+------------------------------------------------------------------+
void CollectSwings(ENUM_TIMEFRAMES tf, int piv, datetime tj, double &highs[], double &lows[])
  {
   if(piv <= 0) return;
   MqlRates r[];
   int need = 300 + 2*piv;
   int got = GetRates(tf, need, r);
   if(got < 2*piv+2) return;
   int sec = PeriodSeconds(tf);
   // r[0] is forming. A pivot at i needs piv newer candles (i-1..i-piv) and piv older (i+1..i+piv); it is confirmed at
   // the close of candle i-piv. Older side strictly beyond, newer side may be equal (as in the backtest).
   for(int i=got-piv-1; i>=1+piv; i--)
     {
      bool isHigh=true, isLow=true;
      for(int k=1;k<=piv;k++)
        {
         if(r[i+k].high >= r[i].high || r[i-k].high >  r[i].high) isHigh=false;
         if(r[i+k].low  <= r[i].low  || r[i-k].low  <  r[i].low ) isLow=false;
        }
      datetime ct = r[i-piv].time + sec;
      if(ct > tj) continue;
      if(isHigh && LevelAlive(r[i].high, true,  ct, tj)) AppendIf(highs, r[i].high);
      if(isLow  && LevelAlive(r[i].low,  false, ct, tj)) AppendIf(lows,  r[i].low);
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
   CollectSwings(PERIOD_MN1, InpPivDWM, tj, highs, lows);
   CollectSwings(PERIOD_W1, InpPivDWM, tj, highs, lows);
   CollectSwings(PERIOD_D1, InpPivDWM, tj, highs, lows);
   if(InpPiv4H>0) CollectSwings(PERIOD_H4, InpPiv4H, tj, highs, lows);
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
   LoadH1Cache();
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

      bool ok = TryBuild(g_sweeps[s].isShort, g_sweeps[s].extreme, g_sweeps[s].time);
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
//| Rules 2-3 for the sweep registered at sweepTime (short; long       |
//| mirrored). Called on every newly closed 1H candle while the sweep  |
//| is alive.                                                          |
//|  - the 4H FVG: the NEWEST bullish 4H FVG whose middle candle is at |
//|    or before the 4H candle of the sweep, starting at most          |
//|    InpLegLookback4H 4H candles before it, complete when this 1H    |
//|    candle opened, and intact (no 1H close below it between its     |
//|    completion and the sweep candle);                               |
//|  - this 1H candle CLOSES below it (inversion);                     |
//|  - 1H displacement (consecutive bearish closes, >= InpDispATR ATR);|
//|  - 1H MSS: a close (from the sweep extreme on) below the last      |
//|    confirmed 1H swing low that formed before the extreme.          |
//+------------------------------------------------------------------+
bool TryBuild(bool sh, double sweepExt, datetime sweepTime)
  {
   MqlRates h4[]; int n4 = GetChrono(PERIOD_H4, InpLegLookback4H+60, h4); if(n4 < 12) return false;
   MqlRates h1[]; int n1 = GetChrono(PERIOD_H1, 600, h1);                if(n1 < 80) return false;
   int L = n1-2;                                          // the just-closed 1H candle (n1-1 is still forming)
   int sec4 = PeriodSeconds(PERIOD_H4);
   int s4 = -1, s1 = -1;
   for(int k=n4-2;k>=0;k--) if(h4[k].time <= sweepTime) { s4=k; break; }
   for(int k=L;k>=0;k--)    if(h1[k].time <= sweepTime) { s1=k; break; }
   if(s4 < 0 || s1 < 0) return false;
   int origin = MathMax(0, s4 - InpLegLookback4H);

   int fi=-1; double bot=0, top=0;
   for(int i=MathMin(s4+1, n4-2); i>=origin+2 && i>=2; i--)        // i = candle 3 of the FVG; middle candle i-1 <= s4
     {
      datetime end4 = h4[i].time + sec4;
      if(end4 > h1[L].time) continue;                              // not complete when this 1H candle opened
      bool bull = h4[i].low  > h4[i-2].high;
      bool bear = h4[i].high < h4[i-2].low;
      if(sh ? !bull : !bear) continue;
      double b_ = sh ? h4[i-2].high : h4[i].high;
      double t_ = sh ? h4[i].low    : h4[i-2].low;
      bool intact = true;
      for(int k=0; k<s1 && intact; k++)
        {
         if(h1[k].time < end4) continue;
         if(sh ? h1[k].close < b_ : h1[k].close > t_) intact = false;
        }
      if(!intact) continue;
      fi=i; bot=b_; top=t_; break;                                 // newest first
     }
   if(fi < 0) return false;

   if(sh ? h1[L].close >= bot : h1[L].close <= top) return false;  // the inversion

   double atr = ATR14c(h1, L);
   int run=0; double runOpen=h1[L].open;
   for(int k=L;k>=0;k--)
     {
      if(sh ? h1[k].close < h1[k].open : h1[k].close > h1[k].open) { run++; runOpen=h1[k].open; } else break;
     }
   double move = sh ? runOpen - h1[L].close : h1[L].close - runOpen;
   if(run < 1 || move < InpDispATR*atr) return false;

   int ext = s1;                                                   // the sweep extreme candle (running extreme s1..L)
   for(int k=s1;k<=L;k++) if(sh ? h1[k].high > h1[ext].high : h1[k].low < h1[ext].low) ext = k;
   int p = InpMssPivot, pv = -1;
   for(int i=p; i<=L-p && i<ext; i++)                              // last confirmed 1H swing before the extreme
     {
      bool ok = true;
      for(int k=1;k<=p && ok;k++)
        {
         if(sh) { if(!(h1[i].low  < h1[i-k].low)  || !(h1[i].low  <= h1[i+k].low))  ok=false; }
         else   { if(!(h1[i].high > h1[i-k].high) || !(h1[i].high >= h1[i+k].high)) ok=false; }
        }
      if(ok) pv = i;
     }
   if(pv < 0) return false;
   double mssLv = sh ? h1[pv].low : h1[pv].high;
   bool mss = false;
   for(int t=MathMax(ext, pv+p+1); t<=L; t++)
      if(sh ? h1[t].close < mssLv : h1[t].close > mssLv) { mss = true; break; }
   if(!mss) return false;

   RegisterSetup(sh, top, bot, sweepExt, h1[L].time, h1[ext].time, h4[fi-1].time);
   return true;
  }

//+------------------------------------------------------------------+
//| STOP: 50% of the 1H order block of the drop. FVG of the drop = the |
//| FIRST bearish 1H FVG after the sweep extreme whose top is above the|
//| 4H IFVG bottom; OB = last up-close 1H candle within 4 candles back |
//| from its first candle. No OB: the previous 1H candle high/low     |
//| beyond the entry (24 candles back). (long mirrored)                |
//+------------------------------------------------------------------+
double PrevCandleStop(const MqlRates &r[], int L, bool sh, double entry, double fallback)   // previous completed 1H candle high/low beyond the entry (24 candles back)
  {
   for(int k=L; k>L-24 && k>=0; k--)
     {
      double v = sh ? r[k].high : r[k].low;
      if(sh ? v > entry : v < entry) return v;
     }
   return fallback;
  }

double StopFromOB(bool sh, datetime extTime, double ext, double bot4, double top4, double entry)
  {
   MqlRates r[]; int n = GetChrono(PERIOD_H1, 600, r); if(n < 40) return ext;
   int L = n-2, anc = -1;
   for(int k=L;k>=0;k--) if(r[k].time == extTime) { anc = k; break; }
   if(anc < 0) return PrevCandleStop(r, L, sh, entry, ext);
   for(int i3=MathMax(anc+1,2); i3<=L; i3++)
     {
      bool fvg = sh ? (r[i3].high < r[i3-2].low && r[i3-2].low  > bot4)
                    : (r[i3].low  > r[i3-2].high && r[i3-2].high < top4);
      if(!fvg) continue;
      int c1 = i3-2;
      for(int m=c1; m>=MathMax(c1-3,0); m--)
         if(sh ? r[m].close > r[m].open : r[m].close < r[m].open) return (r[m].high + r[m].low)/2.0;
      break;
     }
   return PrevCandleStop(r, L, sh, entry, ext);       // no order block: previous 1H candle high/low
  }

//+------------------------------------------------------------------+
//| TARGET: the most recent confirmed 1H swing low (short) / high      |
//| (long), 2 candles each side, BEFORE the 4H FVG's middle candle.    |
//| 0 = none beyond the entry (the trade is skipped, as in the test).  |
//+------------------------------------------------------------------+
double TargetSwing(bool sh, datetime fvgMid, double entry)
  {
   MqlRates r[]; int n = GetChrono(PERIOD_H1, 800, r); if(n < 40) return 0;
   int L = n-2, b = -1;
   for(int k=0;k<=L;k++) if(r[k].time >= fvgMid) { b = k; break; }
   if(b < 0) return 0;
   const int p = 2;
   for(int i=b-1; i>=p; i--)
     {
      if(i+p > L) continue;
      double v = sh ? r[i].low : r[i].high;
      bool piv = true;
      for(int k=i-p;k<=i+p;k++) if(sh ? r[k].low < v : r[k].high > v) { piv = false; break; }
      if(!piv) continue;
      return (sh ? v < entry : v > entry) ? v : 0;
     }
   return 0;
  }

//+------------------------------------------------------------------+
void RegisterSetup(bool isShort, double fvgTop, double fvgBot, double ext, datetime t, datetime extTime, datetime fvgMid)
  {
   if(InpBreakerEntry)                                 // also watch for this setup's 1H breaker FVG (second entry)
     {
      g_bw.active = true; g_bw.isShort = isShort; g_bw.fvgTop = fvgTop; g_bw.fvgBot = fvgBot;
      g_bw.ext = ext; g_bw.extTime = extTime; g_bw.fvgMid = fvgMid; g_bw.sigTime = t; g_bw.expire = TimeCurrent() + 250*3600;
     }
   g_setup.magic        = InpMagic;
   g_setup.active       = true;
   g_setup.isShort      = isShort;
   g_setup.fvgTop       = fvgTop;
   g_setup.fvgBot       = fvgBot;
   g_setup.sweepExtreme = ext;
   g_setup.extTime      = extTime;
   g_setup.fvgMid       = fvgMid;
   g_setup.signalTime   = t;
   g_setup.expiry       = t + 3600 + InpValidHours*3600;   // from the close of the signal candle
   g_setup.ordered      = false;
   g_setup.entry        = isShort ? fvgBot : fvgTop;     // limit at the 4H IFVG near edge

   double base = StopFromOB(isShort, extTime, ext, fvgBot, fvgTop, g_setup.entry);
   double buf  = InpStopBuffer * g_point;
   g_setup.stop = isShort ? base + buf : base - buf;
   double risk = MathAbs(g_setup.entry - g_setup.stop);
   if(isShort ? g_setup.stop <= g_setup.entry : g_setup.stop >= g_setup.entry) { g_setup.active=false; return; }   // stop on the wrong side

   double tgt;
   if(InpUseSwingLowTgt)
     {
      tgt = TargetSwing(isShort, fvgMid, g_setup.entry);
      if(tgt == 0) { Print("No 1H swing-low target beyond the entry - 4H IFVG entry skipped."); g_setup.active=false; return; }
     }
   else tgt = isShort ? g_setup.entry - InpFixedR*risk : g_setup.entry + InpFixedR*risk;
   g_setup.target = tgt;

   string msg = StringFormat("%s SETUP %s | limit %.2f  SL %.2f  TP %.2f  (risk %.1f pts)",
                             isShort?"SHORT":"LONG", g_sym, g_setup.entry, g_setup.stop, g_setup.target, risk/g_point);
   Print(msg); Alert(msg); SendNotification(msg);
   if(LiveAllowed()) PlaceOrder(g_setup);
  }

//+------------------------------------------------------------------+
//| 1H breaker + 1H FVG (second entry), short; long mirrored.          |
//| OB = last up-close 1H candle (within 8) before the first bearish   |
//| 1H FVG of the drop from the sweep extreme. Breaker = first later   |
//| 1H CLOSE below its low (within 48 candles). Entry = limit at the   |
//| bottom of the first bearish 1H FVG whose middle candle is at/after |
//| the break candle (completed within 24 candles of it).              |
//| r[] is CHRONOLOGICAL; L = last completed candle. Returns the limit |
//| price (0 = not found).                                             |
//+------------------------------------------------------------------+
double FindBreakerFvg(const MqlRates &r[], int L, bool sh, int anc, double bot4, double top4)
  {
   int c1 = -1;
   for(int i3=MathMax(anc+1,2); i3<=L; i3++)               // first 1H FVG of the drop (smallest i3)
     {
      bool bear = r[i3].high < r[i3-2].low, bull = r[i3].low > r[i3-2].high;
      if(sh && bear && r[i3-2].low  > bot4) { c1 = i3-2; break; }
      if(!sh && bull && r[i3-2].high < top4) { c1 = i3-2; break; }
     }
   if(c1 < 0) return 0;
   int ob = -1;
   for(int m=c1; m>=MathMax(c1-7,0); m--)
      if(sh ? r[m].close > r[m].open : r[m].close < r[m].open) { ob = m; break; }
   if(ob < 0) return 0;
   double lv = sh ? r[ob].low : r[ob].high;
   int b = -1;
   for(int t=ob+1; t<=MathMin(ob+48,L); t++)
      if(sh ? r[t].close < lv : r[t].close > lv) { b = t; break; }
   if(b < 0) return 0;
   for(int i3=b+1; i3<=MathMin(b+24,L); i3++)               // middle candle (i3-1) at/after the break candle
     {
      bool bear = r[i3].high < r[i3-2].low, bull = r[i3].low > r[i3-2].high;
      if(sh && bear)  return r[i3].high;                    // FVG bottom
      if(!sh && bull) return r[i3].low;                     // FVG top
     }
   return 0;
  }

void CheckBreaker()
  {
   if(TimeCurrent() > g_bw.expire) { g_bw.active = false; return; }
   if(g_setupB.active) return;                              // one breaker order at a time
   MqlRates r[]; int n = GetRates(PERIOD_H1, 400, r);       // series: [0] = forming candle
   if(n < 60) return;
   ArraySetAsSeries(r, false);                              // chronological; n-1 = forming candle
   int L = n-2;                                             // last completed candle
   int anc = -1;                                            // the 1H candle of the sweep extreme
   for(int i=L; i>=0; i--) if(r[i].time == g_bw.extTime) { anc = i; break; }
   if(anc < 0) return;
   double lvl = FindBreakerFvg(r, L, g_bw.isShort, anc, g_bw.fvgBot, g_bw.fvgTop);
   if(lvl <= 0) return;

   bool sh = g_bw.isShort;
   g_setupB.magic = InpMagic+1; g_setupB.active = true; g_setupB.isShort = sh;
   g_setupB.extTime = g_bw.extTime; g_setupB.fvgMid = g_bw.fvgMid;
   g_setupB.fvgTop = g_bw.fvgTop; g_setupB.fvgBot = g_bw.fvgBot; g_setupB.sweepExtreme = g_bw.ext;
   g_setupB.signalTime = TimeCurrent(); g_setupB.expiry = TimeCurrent() + InpValidHours*3600; g_setupB.ordered = false;
   g_setupB.entry = lvl;
   double base = StopFromOB(sh, g_bw.extTime, g_bw.ext, g_bw.fvgBot, g_bw.fvgTop, g_setupB.entry);
   double buf  = InpStopBuffer * g_point;
   g_setupB.stop = sh ? base + buf : base - buf;
   double risk = MathAbs(g_setupB.entry - g_setupB.stop);
   g_bw.active = false;                                     // one breaker entry per setup
   if(sh ? g_setupB.stop <= g_setupB.entry : g_setupB.stop >= g_setupB.entry) { g_setupB.active = false; return; }
   double tgt;
   if(InpUseSwingLowTgt)
     {
      tgt = TargetSwing(sh, g_bw.fvgMid, g_setupB.entry);
      if(tgt == 0) { Print("No 1H swing-low target beyond the breaker entry - skipped."); g_setupB.active = false; return; }
     }
   else tgt = sh ? g_setupB.entry - InpFixedR*risk : g_setupB.entry + InpFixedR*risk;
   g_setupB.target = tgt;

   string msg = StringFormat("%s BREAKER FVG SETUP %s | limit %.2f  SL %.2f  TP %.2f  (risk %.1f pts)",
                             sh?"SHORT":"LONG", g_sym, g_setupB.entry, g_setupB.stop, g_setupB.target, risk/g_point);
   Print(msg); Alert(msg); SendNotification(msg);
   if(LiveAllowed()) PlaceOrder(g_setupB);
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

void PlaceOrder(Setup &st)
  {
   if(st.ordered) return;
   if(!LiveAllowed()) return;
   if(RiskHalted()) return;
   if(InpOneTradeAtATime && HasOpenOrPending(st.magic)) { Print("Order skipped: a trade/order already exists."); return; }

   double bid = SymbolInfoDouble(g_sym, SYMBOL_BID), ask = SymbolInfoDouble(g_sym, SYMBOL_ASK);
   if(InpMaxSpread > 0 && (ask-bid) > InpMaxSpread)
     { Print("Spread ", DoubleToString(ask-bid,2), " > max ", DoubleToString(InpMaxSpread,2), " - will retry on the next 1H candle."); return; }

   trade.SetExpertMagicNumber(st.magic);
   string cmt = (st.magic == InpMagic) ? "ICT swing" : "ICT swing breaker";
   int dg = (int)SymbolInfoInteger(g_sym, SYMBOL_DIGITS);
   double e = NormalizeDouble(st.entry,  dg);
   double s = NormalizeDouble(st.stop,   dg);
   double t = NormalizeDouble(st.target, dg);
   double minDist = (double)SymbolInfoInteger(g_sym, SYMBOL_TRADE_STOPS_LEVEL) * g_point;

   // broker rule: a limit must sit at least StopsLevel away from the market on the correct side
   bool limitOK = st.isShort ? (e >= bid + minDist) : (e <= ask - minDist);
   bool useMarket = false;
   if(!limitOK)
     {
      // price is already at/through the entry (the tested model fills on touch): enter at market if the stop is still valid
      double px = st.isShort ? bid : ask;
      bool better = st.isShort ? px >= e : px <= e;           // market price is at least as good as the limit price
      if(!better) { Print("Entry too close to the market for a limit order - skipped."); return; }
      e = px; useMarket = true;
     }
   // stop / target distance rules
   if(MathAbs(e - s) < minDist || MathAbs(t - e) < minDist) { Print("Stop/target closer than the broker minimum - skipped."); return; }
   if(st.isShort ? (s <= e) : (s >= e))                  { Print("Stop on the wrong side after adjusting - skipped.");     return; }

   double lots = LotsForRisk(e, s);
   if(lots <= 0) return;

   // margin check
   double margin = 0;
   if(OrderCalcMargin(st.isShort ? ORDER_TYPE_SELL : ORDER_TYPE_BUY, g_sym, lots, e, margin) &&
      margin > AccountInfoDouble(ACCOUNT_MARGIN_FREE)*0.9)
     { Print("Not enough free margin for ", DoubleToString(lots,2), " lots - skipped."); return; }

   bool ok;
   if(useMarket)
      ok = st.isShort ? trade.Sell(lots, g_sym, 0, s, t, cmt) : trade.Buy(lots, g_sym, 0, s, t, cmt);
   else
     {
      ok = st.isShort
           ? trade.SellLimit(lots, e, g_sym, s, t, ORDER_TIME_SPECIFIED, st.expiry, cmt)
           : trade.BuyLimit (lots, e, g_sym, s, t, ORDER_TIME_SPECIFIED, st.expiry, cmt);
      if(!ok && trade.ResultRetcode()==TRADE_RETCODE_INVALID_EXPIRATION)      // broker rejects expiry: use GTC, EA cancels it itself
         ok = st.isShort
              ? trade.SellLimit(lots, e, g_sym, s, t, ORDER_TIME_GTC, 0, cmt)
              : trade.BuyLimit (lots, e, g_sym, s, t, ORDER_TIME_GTC, 0, cmt);
     }
   if(ok) { st.ordered = true; Print("Order placed: ", useMarket ? "MARKET " : "LIMIT ", DoubleToString(lots,2), " lots @ ", DoubleToString(e,dg),
                                          " SL ", DoubleToString(s,dg), " TP ", DoubleToString(t,dg)); }
   else   Print("Order failed (will retry next 1H candle): ", trade.ResultRetcode(), " ", trade.ResultRetcodeDescription());
  }

//+------------------------------------------------------------------+
//| each new 1H close: cancel a setup if price opened beyond the      |
//| sweep extreme before fill, or if the retest window has expired    |
//+------------------------------------------------------------------+
void UpdateSetup(Setup &st)
  {
   MqlRates h1[]; if(GetRates(PERIOD_H1, 3, h1) < 2) return;
   double o1 = h1[1].open;
   // a setup recovered after a restart has no stored sweep extreme (0): skip the "beyond the extreme" cancel for it
   bool beyond = st.sweepExtreme > 0 &&
                 (st.isShort ? o1 > st.sweepExtreme : o1 < st.sweepExtreme);
   bool expired = TimeCurrent() > st.expiry;
   if(beyond || expired)
     {
      if(HasPending(st.magic)) CancelPending(st.magic);
      if(!HasPosition(st.magic)) st.active = false;           // keep tracking while a position is open (it is managed by SL/TP/BE)
      return;
     }
   // still valid but the order was not placed yet (wide spread, margin, transient error): try again
   if(!st.ordered && LiveAllowed()) PlaceOrder(st);
  }

void CancelPending(ulong magic)
  {
   for(int i=OrdersTotal()-1;i>=0;i--)
     {
      ulong tk = OrderGetTicket(i);
      if(tk==0) continue;
      if(OrderGetInteger(ORDER_MAGIC)==(long)magic && OrderGetString(ORDER_SYMBOL)==g_sym) trade.OrderDelete(tk);
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
      if(!IsOurMagic(PositionGetInteger(POSITION_MAGIC)) || PositionGetString(POSITION_SYMBOL)!=g_sym) continue;
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
      if(!IsOurMagic(PositionGetInteger(POSITION_MAGIC)) || PositionGetString(POSITION_SYMBOL)!=g_sym) continue;
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
