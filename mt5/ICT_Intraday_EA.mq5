//+------------------------------------------------------------------+
//|                                            ICT_Intraday_EA.mq5    |
//|   ICT INTRADAY model only (US100, 5m) - the "snapshot" rules of   |
//|   the TradingView intraday scripts / Python intraday_snap.py:     |
//|   Rule 1 level swept on 5m -> 5m/15m IFVG + 5m BOS/MSS with       |
//|   displacement -> limit at the latest 5m FVG / volume imbalance   |
//|   of the drop -> stop at the 5m breaker; half closed at 3R + stop |
//|   to breakeven, the rest runs to the next Rule 1 swing (v1.10).   |
//|   Flat 15 min before the 17:00 New York close, every day (v1.20). |
//|                                                                   |
//|   SHORT described in the comments; LONG is the mirror image.      |
//|   Works on COMPLETED 5m candles only (no repaint). Attach to any  |
//|   chart timeframe of the symbol - it reads M5 and H1 itself.      |
//|                                                                   |
//|   NOT COMPILED OR TESTED HERE: compile in MetaEditor, run it in   |
//|   the Strategy Tester and on demo before any live use. The Python |
//|   backtest of these rules LOSES money (US100 Oct 2026: -21.6R).   |
//+------------------------------------------------------------------+
#property copyright "ICT Intraday EA"
#property version   "1.30"
#property strict

#include <Trade/Trade.mqh>

//------------------------------------------------------------------ inputs
input group "Mode"
input bool   InpLiveTrading      = true;    // true = automatic orders; false = signals / alerts only
input double InpRiskPct          = 1.0;     // risk per trade (% of balance)
input bool   InpUS100Only        = true;    // trade only on a US100 / NAS100 / USTEC chart
input bool   InpAlerts           = true;    // Alert() popups for setups, orders, fills and exits

input group "Automation safety"
input bool   InpAllowRealAccount = false;   // REAL accounts stay signals-only unless true (demo / prop evaluation accounts trade)
input int    InpMaxOpen          = 0;       // max simultaneous orders + positions of this EA (0 = no limit, as in the backtest)
input double InpMaxSpread        = 8.0;     // do not place orders while the spread is wider (price units; 0 = off)
input double InpDailyLossPct     = 4.0;     // no new trades for the day after equity falls this % from the day's start (0 = off)
input double InpMaxDrawdownPct   = 8.0;     // halt after equity falls this % from its peak (0 = off); InpResetPeak to resume
input bool   InpFlattenOnLimit   = false;   // also close open positions when a loss limit is hit
input bool   InpResetPeak        = false;   // true for one start resets the stored equity peak

input group "Time zone (sessions, macros, D/W/M/4H candles are on New York time)"
input double InpServerGMT        = 0.0;     // broker server time = UTC + this many hours (Exness 0; NY-close brokers 2 / 3). Used in the tester
input bool   InpAutoGMT          = true;    // live only: detect the offset from TimeTradeServer() - TimeGMT()

input group "History"
input int    InpH1Bars           = 30000;   // 1H candles loaded for the D/W/M/4H/1H levels (~5 years)
input int    InpWarmupDays       = 30;      // 5m days replayed at start (levels swept / bias / pending setups)

input group "Rule 1 - liquidity"
input int    InpPivDWM           = 2;       // D / W / M swing size (candles each side)
input int    InpPiv4H            = 10;      // 4H swing size (0 = off)
input bool   InpLiq1H            = true;    // 1H swings with the 4H swing size
input bool   InpSessions         = true;    // Asia / London / NY session highs and lows that are also 1H+ swings
input int    InpSessionDays      = 7;       // session level stays sweepable for N days
input bool   InpFvgLiq4H         = true;    // far edge of every FRESH 4H FVG
input bool   InpFvgLiq1H         = true;    // far edge of every FRESH 1H FVG
input bool   InpFvgLiqD          = true;    // far edge of every FRESH D FVG (v1.30)
input bool   InpMacro            = true;    // ICT macro window highs / lows (NY: 02:33-03:00, 04:03-04:30, 08:50-09:10, 09:50-10:10, 10:50-11:10, 11:50-12:10, 13:10-13:40, 15:15-15:45, 19:50-20:10, 20:50-21:10)
input int    InpMacroHours       = 24;      // macro level stays sweepable for N hours

input group "Rules 2-6"
input double InpSweepDispATR     = 1.0;     // sweep (B): two displacement candles moving >= x ATR14
input int    InpIfvgLookback     = 48;      // IFVG: 5m / 15m FVG completed within N 5m candles before the sweep
input bool   InpIfvg15m          = true;    // the IFVG may also be a 15m FVG
input bool   InpMssBreak         = true;    // the break may also be a post-sweep 5m MSS
input bool   InpBosWick          = true;    // the break may be a body close OR a wick
input int    InpReversal         = 48;      // IFVG + break within N 5m candles of the sweep
input int    InpDispCandles      = 2;       // displacement: >= N candles moving >= x ATR14 (or one candle body >= x ATR14)
input double InpDispATR          = 1.0;     // displacement: x ATR14
input bool   InpBiasFilter       = true;    // only trade in the direction of the last Rule 1 swing sweep (high swept = shorts)

input group "Entry / exit"
input int    InpFvgAfter         = 2;       // entry FVG / VI may complete N candles after the reversal
input int    InpEntryValidMin    = 60;      // limit order valid N minutes after the reversal candle close
input bool   InpOnePerEntry      = true;    // one trade per direction + entry zone / price
input bool   InpPartial          = true;    // close InpPartialPct at InpTargetR, stop to breakeven, rest runs to the next Rule 1 swing
input double InpPartialPct       = 50.0;    // % of the position closed at the first target
input double InpTargetR          = 3.0;     // first target in R (the only target when InpPartial = false)
input bool   InpTargetSwing      = false;   // InpPartial = false only: target = nearest major 5m swing (10 each side), else InpTargetR
input double InpBE_at_R          = 1.0;     // stop to breakeven at +R on completed 5m candles after the fill (0 = off). With InpPartial
input bool   InpBEBeforeTP1      = false;   // ... it is used only if this is true (else the stop moves to breakeven at the first target)
input bool   InpEODClose         = true;    // close all trades InpEODMin minutes before the market close; no entries from then to the reopen
input string InpEODCloseNY       = "17:00"; // market close, New York time (US100 CFD daily close 17:00; cash market 16:00)
input int    InpEODMin           = 15;      // minutes before the close
input ulong  InpMagic            = 770101;  // magic number

//------------------------------------------------------------------ small helpers
int    IMax(int a, int b) { return a > b ? a : b; }
int    IMin(int a, int b) { return a < b ? a : b; }

//------------------------------------------------------------------ globals
CTrade   trade;
string   g_sym;
double   g_point;
bool     g_ready   = false;     // engine initialised (history loaded and replayed)
bool     g_live    = false;     // false during the warm-up replay
bool     g_h1mode  = true;      // true while only 1H history is replayed (before the first 5m candle)
bool     g_hedging = true;
long     g_gmtOff  = 0;         // seconds: server time = UTC + g_gmtOff
bool     g_halted  = false;

int      g_dayKey = 0;
double   g_dayStartEq = 0, g_peakEq = 0;
bool     g_haltedDay = false, g_haltedDD = false;
string   g_gvPeak, g_gvDayKey, g_gvDayEq;

int      g_bias = 0;            // -1 bearish (shorts only), +1 bullish (longs only), 0 none
string   g_biasTx = "-";

//------------------------------------------------------------------ time: server -> UTC -> New York
datetime NthSunday(int y, int mon, int nth)
  {
   MqlDateTime x; ZeroMemory(x);
   x.year = y; x.mon = mon; x.day = 1;
   datetime t = StructToTime(x);
   TimeToStruct(t, x);
   int first = 1 + (7 - x.day_of_week) % 7;               // day of the month of the first Sunday
   return (datetime)((long)t + (long)(first - 1 + 7 * (nth - 1)) * 86400);
  }

int NYOffset(datetime utc)                                 // seconds to add to UTC to get New York local time
  {
   static int cy = -1; static datetime cs = 0, ce = 0;
   MqlDateTime d; TimeToStruct(utc, d);
   if(d.year != cy) { cy = d.year; cs = NthSunday(cy, 3, 2) + 7 * 3600; ce = NthSunday(cy, 11, 1) + 6 * 3600; }
   return (utc >= cs && utc < ce) ? -4 * 3600 : -5 * 3600;
  }

long NYL(datetime srv)                                     // New York local time (seconds) of a server time
  {
   long u = (long)srv - g_gmtOff;
   return u + NYOffset((datetime)u);
  }
long TDay(datetime srv)  { return (NYL(srv) + 7 * 3600) / 86400; }        // trading day (rolls at 17:00 New York)
long Key4H(datetime srv) { return (NYL(srv) + 7 * 3600) / 14400; }        // 4H grid = New York + 7h (MT5 grid of the backtest)
long KeyW(datetime srv)  { return (TDay(srv) - 2) / 7; }                  // trading week (Saturday-based like pandas W-FRI)
long KeyM(datetime srv)  { MqlDateTime d; TimeToStruct((datetime)(TDay(srv) * 86400), d); return (long)d.year * 12 + d.mon; }

//------------------------------------------------------------------ HTF candles built from 1H (D / W / M / 4H on NY time; 1H itself)
class CHtf
  {
public:
   int      id;                 // 0 M, 1 W, 2 D, 3 4H, 4 1H
   int      piv;                // swing size for liquidity (0 = off)
   bool     acc;
   long     key;
   double   ao, ah, al, ac;
   datetime ast, alast;
   double   o[], h[], l[], c[];
   datetime st[], en[];
   int      n;
   void     Init(int _id, int _piv) { id = _id; piv = _piv; acc = false; n = 0; }
   void     Push(double O, double H, double L, double C, datetime S, datetime E)
     {
      if(n >= ArraySize(o))
        {
         int m = n + 2048;
         ArrayResize(o, m); ArrayResize(h, m); ArrayResize(l, m); ArrayResize(c, m); ArrayResize(st, m); ArrayResize(en, m);
        }
      o[n] = O; h[n] = H; l[n] = L; c[n] = C; st[n] = S; en[n] = E; n++;
     }
   // add one 1H candle; k = its candle key, kNext = key of the following hour (a change = this 1H candle closes the candle)
   void     Feed(double O, double H, double L, double C, datetime t, long k, long kNext)
     {
      if(acc && k != key) { Push(ao, ah, al, ac, ast, alast + 3600); acc = false; }
      if(!acc) { acc = true; key = k; ao = O; ah = H; al = L; ac = C; ast = t; alast = t; }
      else     { ah = MathMax(ah, H); al = MathMin(al, L); ac = C; alast = t; }
      if(kNext != k) { Push(ao, ah, al, ac, ast, alast + 3600); acc = false; }
     }
  };
CHtf g_M, g_W, g_D, g_4, g_1;

//------------------------------------------------------------------ Rule 1 levels
struct Lvl
  {
   int      tf;                 // 0 M,1 W,2 D,3 4H,4 1H,5 ASIA,6 LONDON,7 NY,8 4HFVG,9 1HFVG,10 MACRO,11 DFVG
   bool     hi;                 // true = buy-side level (high)
   double   px;
   datetime ct;                 // sweepable by 5m candles opening at / after this time
   datetime ex;                 // ... and opening at / before this time (0 = no end)
   bool     used;               // swept (or expired)
   double   nearE;              // FVG levels: the near edge (trading through it ends "fresh")
   int      fIdx;               // FVG levels: candle-3 index on its timeframe
  };
Lvl    g_lv[];
string TFN[12] = {"M", "W", "D", "4H", "1H", "ASIA", "LONDON", "NY", "4HFVG", "1HFVG", "MACRO", "DFVG"};

void AddLevel(int tf, bool hi, double px, datetime ct, datetime ex, double nearE = 0, int fIdx = -1)
  {
   int n = ArraySize(g_lv);
   ArrayResize(g_lv, n + 1, 4096);
   g_lv[n].tf = tf; g_lv[n].hi = hi; g_lv[n].px = px; g_lv[n].ct = ct; g_lv[n].ex = ex;
   g_lv[n].used = false; g_lv[n].nearE = nearE; g_lv[n].fIdx = fIdx;
  }

// swing prices (1H 2 each side, 4H / D / W / M with their sizes) used to keep a session extreme only if it is also a swing
double g_spHi[], g_spLo[];
void PushD(double &a[], double v) { int n = ArraySize(a); ArrayResize(a, n + 1, 4096); a[n] = v; }

struct PendS { int sid; bool hi; double px; datetime end; datetime ex; };
PendS g_ps[];
int      g_sAccId = -1;
long     g_sAccTd = 0;
double   g_sAccH = 0, g_sAccL = 0;
datetime g_sAccLast = 0;

//------------------------------------------------------------------ 5m candles (absolute indices, trimmed from the front)
double   g5o[], g5h[], g5l[], g5c[], g5tr[], g5atr[];
datetime g5t[];
int      g5base = 0, g5cnt = 0;
int      N5()        { return g5base + g5cnt; }
double   O5(int i)   { return g5o[i - g5base]; }
double   H5(int i)   { return g5h[i - g5base]; }
double   L5(int i)   { return g5l[i - g5base]; }
double   C5(int i)   { return g5c[i - g5base]; }
double   A5(int i)   { return g5atr[i - g5base]; }
datetime T5(int i)   { return g5t[i - g5base]; }

// zones: 5m FVGs, 15m FVGs (index = the 5m candle at whose close they complete), 5m volume imbalances
struct Zn { int dir; double top, bot; int idx; int start; bool vi; bool m15; };
Zn g_f5[], g_f15[], g_vi[];

long     g_a15k = -1;
double   g_a15h = 0, g_a15l = 0;
double   g_q15h[], g_q15l[];

// ICT macro windows, NY minutes (start floored to the 5m candle containing it, end)
int      MCS[10] = {150, 240, 530, 590, 650, 710, 790, 915, 1190, 1250};
int      MCE[10] = {180, 270, 550, 610, 670, 730, 820, 945, 1210, 1270};
int      g_macW = -1;
long     g_macDay = 0;
double   g_macH = 0, g_macL = 0;
long     g_macOff = 0;

// a swept level waiting for the IFVG + break
struct Sw
  {
   bool   sh;
   int    s;                    // 5m candle that confirmed the sweep
   int    origin;               // leg origin (BOS level candle)
   double olv;
   double fTop, fBot;           // the FVG to invert
   int    fIdx;
   bool   f15;
   int    ex;                   // running sweep extreme
   int    msI;                  // post-sweep 5m swing low (short) = MSS level
   bool   inv;
   int    brk;                  // candle of the low that was broken
   int    tf;
   double px;
  };
Sw g_sw[];

// a setup (reversal candle j) -> entry zone -> limit order -> trade
struct Sg
  {
   bool     sh;
   int      j;
   datetime revClose, expiry;
   double   stop;
   int      ext;
   int      fIdx; bool f15;
   double   zTop, zBot; int zIdx; bool zVI;
   double   level;
   int      liveFrom;
   int      state;              // 0 waiting for the entry zone, 1 order, 2 filled (model), 3 done
   double   entry, tp, vstop, risk;
   bool     be;
   double   tp1, tp2;           // partial: first target / runner target (0 = none -> everything at tp1)
   int      halfIdx;            // candle where the model closed the first part (-1 = not yet)
   int      fillIdx;
   ulong    ticket;             // real pending order (0 = none)
   bool     want;               // a real order should be working
   string   id;
   string   info;
  };
Sg g_sg[];

int    g_vTrades = 0, g_vWins = 0;
long   g_eodDay = -1;                    // NY day of the last end-of-day flatten

// end of day: minutes of the New York day; NYMin = New York minute of a server time
int  EODClose() { return (int)StringToInteger(StringSubstr(InpEODCloseNY, 0, 2)) * 60 + (int)StringToInteger(StringSubstr(InpEODCloseNY, 3, 2)); }
int  NYMin(datetime srv) { return (int)((NYL(srv) % 86400) / 60); }
bool InEOD(datetime srv)                 // from the cutoff (close - InpEODMin) to the close: flat, no entries
  {
   if(!InpEODClose) return false;
   int m = NYMin(srv), c = EODClose();
   return m >= c - InpEODMin && m < c;
  }
bool EODCandle(datetime start5)          // 5m candle ending at / after the cutoff -> the model closes at its close
  {
   if(!InpEODClose) return false;
   int m = NYMin(start5), c = EODClose();
   return m + 5 >= c - InpEODMin && m < c;
  }
double g_vR = 0;
int    g_steps = 0, g_h1steps = 0;

MqlRates g_h1all[];
int      g_h1ptr = 0;
datetime g_last5 = 0, g_forming = 0;

//+------------------------------------------------------------------+
int OnInit()
  {
   g_sym = _Symbol;
   g_point = _Point;
   trade.SetExpertMagicNumber(InpMagic);
   g_hedging = (AccountInfoInteger(ACCOUNT_MARGIN_MODE) == ACCOUNT_MARGIN_MODE_RETAIL_HEDGING);
   if(!g_hedging) Print("Netting account: the EA holds one order / position at a time (the model can overlap trades).");
   if(InpUS100Only && !IsUS100()) Print("Not a US100 chart - EA idle. Symbol: ", g_sym);

   long login = AccountInfoInteger(ACCOUNT_LOGIN);
   g_gvPeak   = "ICTINTRA_PEAK_"   + IntegerToString((int)login);
   g_gvDayKey = "ICTINTRA_DAYKEY_" + IntegerToString((int)login);
   g_gvDayEq  = "ICTINTRA_DAYEQ_"  + IntegerToString((int)login);
   double eq = AccountInfoDouble(ACCOUNT_EQUITY);
   if(InpResetPeak) GlobalVariableDel(g_gvPeak);
   g_peakEq = GlobalVariableCheck(g_gvPeak) ? GlobalVariableGet(g_gvPeak) : eq;
   if(eq > g_peakEq) g_peakEq = eq;
   GlobalVariableSet(g_gvPeak, g_peakEq);
   if(GlobalVariableCheck(g_gvDayKey) && GlobalVariableCheck(g_gvDayEq))
     { g_dayKey = (int)GlobalVariableGet(g_gvDayKey); g_dayStartEq = GlobalVariableGet(g_gvDayEq); }

   if(InpLiveTrading && !InpAllowRealAccount && AccountInfoInteger(ACCOUNT_TRADE_MODE) == ACCOUNT_TRADE_MODE_REAL)
      Print("REAL account and InpAllowRealAccount=false -> SIGNALS ONLY.");

   g_gmtOff = (long)MathRound(InpServerGMT * 3600.0);
   if(InpAutoGMT && !MQLInfoInteger(MQL_TESTER))
     {
      long d = (long)(TimeTradeServer() - TimeGMT());
      if(MathAbs((double)d) <= 14 * 3600) g_gmtOff = (long)MathRound(d / 900.0) * 900;
     }
   Print("ICT Intraday EA: server time = UTC ", (g_gmtOff >= 0 ? "+" : ""), DoubleToString(g_gmtOff / 3600.0, 2),
         "h | mode ", LiveAllowed() ? "AUTOMATIC" : "SIGNALS ONLY", " | risk ", DoubleToString(InpRiskPct, 2), "%");
   EventSetTimer(5);
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
   Comment("");
   Print("ICT Intraday EA stopped. Model trades since start of the replay: ", g_vTrades, ", wins ", g_vWins,
         ", ", DoubleToString(g_vR, 2), "R before costs.");
  }

void OnTimer() { if(!g_ready) OnTick(); }

bool LiveAllowed()
  {
   if(!InpLiveTrading) return false;
   if(AccountInfoInteger(ACCOUNT_TRADE_MODE) == ACCOUNT_TRADE_MODE_REAL && !InpAllowRealAccount) return false;
   return true;
  }

bool IsUS100()
  {
   string s = g_sym; StringToUpper(s);
   string k[] = {"NAS100", "US100", "USTEC", "NDX", "USTECH", "NQ", "US TECH"};
   for(int i = 0; i < ArraySize(k); i++) if(StringFind(s, k[i]) >= 0) return true;
   return false;
  }

void Notify(string msg)
  {
   if(!g_live) return;
   Print(msg);
   if(InpAlerts) Alert(g_sym, " ", msg);
  }

//+------------------------------------------------------------------+
//| engine start: load 1H history, replay it (levels), then replay    |
//| the last InpWarmupDays of 5m candles without trading               |
//+------------------------------------------------------------------+
bool InitEngine()
  {
   ArraySetAsSeries(g_h1all, false);
   int n1 = CopyRates(g_sym, PERIOD_H1, 1, InpH1Bars, g_h1all);
   if(n1 < 300) { Print("Waiting for 1H history (", n1, ")..."); return false; }
   MqlRates m5[]; ArraySetAsSeries(m5, false);
   int want5 = IMax(InpWarmupDays, 3) * 288;
   int n5 = CopyRates(g_sym, PERIOD_M5, 1, want5, m5);
   if(n5 < 500) { Print("Waiting for 5m history (", n5, ")..."); return false; }

   g_M.Init(0, InpPivDWM); g_W.Init(1, InpPivDWM); g_D.Init(2, InpPivDWM);
   g_4.Init(3, InpPiv4H);  g_1.Init(4, InpLiq1H ? InpPiv4H : 0);
   g_h1ptr = 0; g_live = false; g_h1mode = true;

   FeedH1Until(m5[0].time);                    // 1H-only replay: levels swept by a 1H wick + close back
   g_h1mode = false;
   for(int i = 0; i < n5; i++) Step5(m5[i]);   // 5m replay (no orders)
   g_last5 = m5[n5 - 1].time;
   g_forming = iTime(g_sym, PERIOD_M5, 0);
   g_live = true;
   g_ready = true;

   int alive = 0;
   for(int i = 0; i < ArraySize(g_lv); i++) if(!g_lv[i].used) alive++;
   Print("Engine ready: ", n1, " 1H + ", n5, " 5m candles replayed | live levels ", alive, " | bias ", g_biasTx,
         " | model trades in the replay ", g_vTrades, " (", DoubleToString(g_vR, 2), "R before costs)");

   // setups whose order is still valid now: adopt an existing order with the same comment, else place one
   for(int k = 0; k < ArraySize(g_sg); k++)
     {
      if(g_sg[k].state != 1 || TimeCurrent() >= g_sg[k].expiry) continue;
      g_sg[k].want = true;
      ulong tk = FindPending(g_sg[k].id);
      if(tk > 0) { g_sg[k].ticket = tk; Print("Adopted pending order #", tk, " for ", g_sg[k].id); }
      else PlaceReal(k);
     }
   return true;
  }

//+------------------------------------------------------------------+
void OnTick()
  {
   if(InpUS100Only && !IsUS100()) return;
   if(!g_ready) { if(!InitEngine()) return; }

   g_halted = RiskHalted();
   if(g_halted) HandleHalt();

   if(InEOD(TimeCurrent())) FlattenEOD();       // per tick: flat from the cutoff to the market close
   else ManagePartial();                        // per tick: first target -> partial close + breakeven
   // per tick: expire pending orders
   for(int k = 0; k < ArraySize(g_sg); k++)
      if(g_sg[k].ticket > 0 && g_sg[k].want && TimeCurrent() >= g_sg[k].expiry) { CancelReal(k); }

   datetime f0 = iTime(g_sym, PERIOD_M5, 0);
   if(f0 == 0 || f0 == g_forming) return;

   // new 5m candle(s): refresh 1H history, process every completed 5m candle not seen yet
   RefreshH1(f0);
   MqlRates r[]; ArraySetAsSeries(r, false);
   int got = CopyRates(g_sym, PERIOD_M5, g_last5 + 1, f0 - 1, r);
   if(got < 0) return;                          // history not ready: try again on the next tick
   for(int i = 0; i < got; i++)
     {
      if(r[i].time <= g_last5 || r[i].time >= f0) continue;
      Step5(r[i]);
      g_last5 = r[i].time;
     }
   g_forming = f0;
   NewBarMaintenance();
   ShowStatus();
  }

void RefreshH1(datetime f0)
  {
   int n = ArraySize(g_h1all);
   datetime last = n > 0 ? g_h1all[n - 1].time : 0;
   MqlRates r[]; ArraySetAsSeries(r, false);
   int got = CopyRates(g_sym, PERIOD_H1, last + 1, f0, r);
   for(int i = 0; i < got; i++)
     {
      if(r[i].time <= last || r[i].time + 3600 > f0) continue;   // only completed 1H candles
      int m = ArraySize(g_h1all);
      ArrayResize(g_h1all, m + 1, 1024);
      g_h1all[m] = r[i];
      last = r[i].time;
     }
  }

void FeedH1Until(datetime t)
  {
   int n = ArraySize(g_h1all);
   while(g_h1ptr < n && g_h1all[g_h1ptr].time + 3600 <= t)
     {
      ProcessH1(g_h1all[g_h1ptr]);
      g_h1ptr++;
     }
  }

//+------------------------------------------------------------------+
//| one completed 1H candle: HTF candles, swings, FVG edges, sessions |
//+------------------------------------------------------------------+
void FeedTF(CHtf &x, const MqlRates &b, long k, long kNext)
  {
   int n0 = x.n;
   x.Feed(b.open, b.high, b.low, b.close, b.time, k, kNext);
   for(int i = n0; i < x.n; i++) OnCandle(x, i);
  }

void ProcessH1(const MqlRates &b)
  {
   datetime t = b.time;
   FeedTF(g_1, b, (long)t / 3600, (long)t / 3600 + 1);
   FeedTF(g_4, b, Key4H(t), Key4H(t + 3600));
   FeedTF(g_D, b, TDay(t), TDay(t + 3600));
   FeedTF(g_W, b, KeyW(t), KeyW(t + 3600));
   FeedTF(g_M, b, KeyM(t), KeyM(t + 3600));
   if(InpSessions) SessionFeed(b);
   if(InpSessions) PendingSessions(t + 3600);
   if(g_h1mode) H1Consume(b);
   if(++g_h1steps % 500 == 0) CompactLevels();
  }

bool PivHi(const double &a[], int i, int p)
  {
   for(int k = 1; k <= p; k++) if(a[i - k] >= a[i] || a[i + k] > a[i]) return false;
   return true;
  }
bool PivLo(const double &a[], int i, int p)
  {
   for(int k = 1; k <= p; k++) if(a[i - k] <= a[i] || a[i + k] < a[i]) return false;
   return true;
  }

void OnCandle(CHtf &x, int i)
  {
   bool fvgOn = (x.id == 3 && InpFvgLiq4H) || (x.id == 4 && InpFvgLiq1H) || (x.id == 2 && InpFvgLiqD);
   int  ftf = x.id == 3 ? 8 : (x.id == 4 ? 9 : 11);
   // freshness: a later candle trading into the gap ends the FVG level after this candle
   if(fvgOn)
      for(int k = 0; k < ArraySize(g_lv); k++)
        {
         if(g_lv[k].tf != ftf || g_lv[k].used || g_lv[k].ex != 0 || g_lv[k].fIdx >= i) continue;
         if(g_lv[k].hi ? x.h[i] >= g_lv[k].nearE : x.l[i] <= g_lv[k].nearE) g_lv[k].ex = x.en[i] - 1;
        }
   // swing liquidity: pivot with p candles each side, confirmed at the close of candle i
   int p = x.piv;
   if(p > 0 && i - 2 * p >= 0)
     {
      int pv = i - p;
      if(PivHi(x.h, pv, p)) AddLevel(x.id, true,  x.h[pv], x.en[i], 0);
      if(PivLo(x.l, pv, p)) AddLevel(x.id, false, x.l[pv], x.en[i], 0);
     }
   // swing prices for the session filter (1H: 2 each side; 4H / D / W / M: their own size)
   int ps = x.id == 4 ? 2 : (x.id == 3 ? InpPiv4H : InpPivDWM);
   if(ps > 0 && i - 2 * ps >= 0)
     {
      int pv = i - ps;
      if(PivHi(x.h, pv, ps)) PushD(g_spHi, x.h[pv]);
      if(PivLo(x.l, pv, ps)) PushD(g_spLo, x.l[pv]);
     }
   // new FVG completed by this candle -> its far edge is a level
   if(fvgOn && i >= 2)
     {
      if(x.h[i] < x.l[i - 2]) AddLevel(ftf, true,  x.l[i - 2], x.en[i], 0, x.h[i], i);   // bearish FVG: top, near edge = bottom
      if(x.l[i] > x.h[i - 2]) AddLevel(ftf, false, x.h[i - 2], x.en[i], 0, x.l[i], i);   // bullish FVG: bottom, near edge = top
     }
  }

int SessionOf(datetime t)
  {
   int nyh = (int)((NYL(t) % 86400) / 3600);
   if(nyh >= 20) return 0;
   if(nyh >= 2 && nyh < 5) return 1;
   if(nyh >= 7 && nyh < 10) return 2;
   return -1;
  }

void FinalizeSession()
  {
   if(g_sAccId < 0) return;
   datetime end = g_sAccLast + 3600;
   for(int s = 0; s < 2; s++)
     {
      int n = ArraySize(g_ps); ArrayResize(g_ps, n + 1, 64);
      g_ps[n].sid = g_sAccId; g_ps[n].hi = (s == 0); g_ps[n].px = (s == 0) ? g_sAccH : g_sAccL;
      g_ps[n].end = end; g_ps[n].ex = end + InpSessionDays * 86400;
     }
   g_sAccId = -1;
  }

void SessionFeed(const MqlRates &b)
  {
   int  sid = SessionOf(b.time);
   long td  = TDay(b.time);
   if(g_sAccId >= 0 && (sid != g_sAccId || td != g_sAccTd)) FinalizeSession();
   if(sid < 0) return;
   if(g_sAccId < 0) { g_sAccId = sid; g_sAccTd = td; g_sAccH = b.high; g_sAccL = b.low; }
   else             { g_sAccH = MathMax(g_sAccH, b.high); g_sAccL = MathMin(g_sAccL, b.low); }
   g_sAccLast = b.time;
   datetime nx = b.time + 3600;
   if(SessionOf(nx) != sid || TDay(nx) != td) FinalizeSession();
  }

bool IsSwingPrice(double px, bool hi)
  {
   double tol = px * 0.0001;
   int n = hi ? ArraySize(g_spHi) : ArraySize(g_spLo);
   for(int i = n - 1; i >= 0; i--)
      if(MathAbs((hi ? g_spHi[i] : g_spLo[i]) - px) <= tol) return true;
   return false;
  }

// a completed session extreme becomes a level once it is (also) a 1H+ swing; checked until it expires
void PendingSessions(datetime now)
  {
   for(int k = ArraySize(g_ps) - 1; k >= 0; k--)
     {
      bool drop = now > g_ps[k].ex;
      if(!drop && IsSwingPrice(g_ps[k].px, g_ps[k].hi))
        {
         AddLevel(5 + g_ps[k].sid, g_ps[k].hi, g_ps[k].px, now <= g_ps[k].end ? g_ps[k].end : now, g_ps[k].ex);
         drop = true;
        }
      if(drop)
        {
         int n = ArraySize(g_ps);
         for(int m = k; m < n - 1; m++) g_ps[m] = g_ps[m + 1];
         ArrayResize(g_ps, n - 1);
        }
     }
  }

void SetBias(int tf, bool hi, double px)
  {
   if(tf > 4) return;                                        // only D / W / M / 4H / 1H swing sweeps set the bias
   g_bias = hi ? -1 : 1;
   g_biasTx = (hi ? "Bearish (" : "Bullish (") + TFN[tf] + (hi ? " high " : " low ") + DoubleToString(px, _Digits) + ")";
  }

// before the 5m replay: a level counts as swept by a 1H candle that wicks through it and closes back
void H1Consume(const MqlRates &b)
  {
   for(int k = 0; k < ArraySize(g_lv); k++)
     {
      if(g_lv[k].used || g_lv[k].ct > b.time) continue;
      if(g_lv[k].ex > 0 && b.time > g_lv[k].ex) { g_lv[k].used = true; continue; }
      double px = g_lv[k].px;
      if(g_lv[k].hi ? (b.high > px && b.close < px) : (b.low < px && b.close > px))
        { g_lv[k].used = true; SetBias(g_lv[k].tf, g_lv[k].hi, px); }
     }
  }

//+------------------------------------------------------------------+
//| one completed 5m candle                                           |
//+------------------------------------------------------------------+
void Step5(const MqlRates &b)
  {
   FeedH1Until(b.time);
   Add5(b);
   int i = N5() - 1;
   Zones5(i);
   if(InpIfvg15m) Agg15(i);
   if(InpMacro) MacroStep(i);
   SignalsModel(i);                 // fills / exits / expiry of the existing setups (orders were set on earlier candles)
   ScanSweeps(i);                   // Rule 1 levels swept on this candle
   ProgressSweeps(i);               // IFVG + break + displacement -> setup
   RefineSignals(i);                // entry zone chosen / refined, order placed
   if(++g_steps % 500 == 0) Compact();
  }

void Add5(const MqlRates &b)
  {
   if(g5cnt >= ArraySize(g5o))
     {
      int m = g5cnt + 4096;
      ArrayResize(g5o, m); ArrayResize(g5h, m); ArrayResize(g5l, m); ArrayResize(g5c, m);
      ArrayResize(g5tr, m); ArrayResize(g5atr, m); ArrayResize(g5t, m);
     }
   int p = g5cnt;
   g5o[p] = b.open; g5h[p] = b.high; g5l[p] = b.low; g5c[p] = b.close; g5t[p] = b.time;
   double tr = b.high - b.low;
   if(p > 0) tr = MathMax(tr, MathMax(MathAbs(b.high - g5c[p - 1]), MathAbs(b.low - g5c[p - 1])));
   g5tr[p] = tr;
   double s = 0; int cnt = 0;
   for(int k = p; k >= 0 && cnt < 14; k--) { s += g5tr[k]; cnt++; }
   g5atr[p] = s / cnt;
   g5cnt++;
  }

void PushZ(Zn &a[], int dir, double top, double bot, int idx, int start, bool vi, bool m15)
  {
   int n = ArraySize(a); ArrayResize(a, n + 1, 512);
   a[n].dir = dir; a[n].top = top; a[n].bot = bot; a[n].idx = idx; a[n].start = start; a[n].vi = vi; a[n].m15 = m15;
  }

void Zones5(int i)
  {
   if(i - 2 >= g5base)
     {
      if(L5(i) > H5(i - 2)) PushZ(g_f5,  1, L5(i), H5(i - 2), i, i - 2, false, false);
      if(H5(i) < L5(i - 2)) PushZ(g_f5, -1, L5(i - 2), H5(i), i, i - 2, false, false);
     }
   if(i - 1 >= g5base)                       // volume imbalance between candles i-1 and i
     {
      double o1 = O5(i - 1), c1 = C5(i - 1), o2 = O5(i), c2 = C5(i);
      double b1lo = MathMin(o1, c1), b1hi = MathMax(o1, c1), b2lo = MathMin(o2, c2), b2hi = MathMax(o2, c2);
      bool bear2 = c1 < o1 && c2 < o2, bull2 = c1 > o1 && c2 > o2;
      if(bear2 && b1lo > b2hi && H5(i) >= L5(i - 1)) PushZ(g_vi, -1, b1lo, b2hi, i, i - 1, true, false);
      if(bull2 && b1hi < b2lo && L5(i) <= H5(i - 1)) PushZ(g_vi,  1, b2lo, b1hi, i, i - 1, true, false);
      if(bear2 && o2 > c1)                           PushZ(g_vi, -1, o2, c1, i, i - 1, true, false);
      if(bull2 && o2 < c1)                           PushZ(g_vi,  1, c1, o2, i, i - 1, true, false);
     }
  }

void Close15(int idx)
  {
   PushD(g_q15h, g_a15h); PushD(g_q15l, g_a15l);
   int n = ArraySize(g_q15h);
   if(n >= 3)
     {
      if(g_q15l[n - 1] > g_q15h[n - 3]) PushZ(g_f15,  1, g_q15l[n - 1], g_q15h[n - 3], idx, idx, false, true);
      if(g_q15h[n - 1] < g_q15l[n - 3]) PushZ(g_f15, -1, g_q15l[n - 3], g_q15h[n - 1], idx, idx, false, true);
     }
   g_a15k = -1;
  }

void Agg15(int i)                            // 15m candles on the UTC 15-minute clock, built from the 5m candles
  {
   long k = ((long)T5(i)) / 900;
   if(g_a15k >= 0 && k != g_a15k) Close15(i - 1);
   if(g_a15k < 0) { g_a15k = k; g_a15h = H5(i); g_a15l = L5(i); }
   else           { g_a15h = MathMax(g_a15h, H5(i)); g_a15l = MathMin(g_a15l, L5(i)); }
   if((((long)T5(i)) + 300) % 900 == 0) Close15(i);
  }

void FinalizeMacro()
  {
   if(g_macW < 0) return;
   long endNY = g_macDay * 86400 + (long)MCE[g_macW] * 60;
   datetime ct = (datetime)(endNY - g_macOff + g_gmtOff);
   AddLevel(10, true,  g_macH, ct, ct + InpMacroHours * 3600);
   AddLevel(10, false, g_macL, ct, ct + InpMacroHours * 3600);
   g_macW = -1;
  }

void MacroStep(int i)
  {
   long ny = NYL(T5(i));
   int mins = (int)((ny % 86400) / 60);
   long day = ny / 86400;
   int w = -1;
   for(int k = 0; k < 10; k++) if(mins >= MCS[k] && mins < MCE[k]) w = k;
   if(g_macW >= 0 && (w != g_macW || day != g_macDay)) FinalizeMacro();
   if(w < 0) return;
   if(g_macW < 0)
     {
      g_macW = w; g_macDay = day; g_macH = H5(i); g_macL = L5(i);
      long u = (long)T5(i) - g_gmtOff;
      g_macOff = NYOffset((datetime)u);
     }
   else { g_macH = MathMax(g_macH, H5(i)); g_macL = MathMin(g_macL, L5(i)); }
   if(mins + 5 >= MCE[w]) FinalizeMacro();
  }

//+------------------------------------------------------------------+
//| Rule 2: 5m sweep of a live level on candle i                      |
//|  (A) wick through + close back; (B) 1 or 2 candles close beyond,  |
//|  then two displacement candles (>= x ATR14), the second closing   |
//|  beyond the low (high) of the first sweeping candle.              |
//+------------------------------------------------------------------+
void ScanSweeps(int i)
  {
   datetime t = T5(i);
   int n = ArraySize(g_lv);
   for(int li = 0; li < n; li++)
     {
      if(g_lv[li].used || g_lv[li].ct > t) continue;
      if(g_lv[li].ex > 0 && t > g_lv[li].ex) { g_lv[li].used = true; continue; }
      double px = g_lv[li].px;
      bool   hi = g_lv[li].hi;
      datetime ct = g_lv[li].ct, ex = g_lv[li].ex;
      bool ev = hi ? (H5(i) > px && C5(i) < px) : (L5(i) < px && C5(i) > px);
      int k = i - 2;
      if(!ev && k >= g5base && T5(k) >= ct && (ex == 0 || T5(k) <= ex))
        {
         bool p1 = k - 1 >= g5base && T5(k - 1) >= ct && (hi ? C5(k - 1) > px : C5(k - 1) < px);
         bool p2 = k - 2 >= g5base && T5(k - 2) >= ct && (hi ? C5(k - 2) > px : C5(k - 2) < px);
         bool thr = (hi ? C5(k) > px : C5(k) < px) && !(p1 && p2);
         bool dsp = hi ? (C5(k + 1) < O5(k + 1) && C5(i) < O5(i) && (O5(k + 1) - C5(i)) >= InpSweepDispATR * A5(i))
                       : (C5(k + 1) > O5(k + 1) && C5(i) > O5(i) && (C5(i) - O5(k + 1)) >= InpSweepDispATR * A5(i));
         double ref = hi ? (p1 ? L5(k - 1) : L5(k)) : (p1 ? H5(k - 1) : H5(k));
         ev = thr && dsp && (hi ? C5(i) < ref : C5(i) > ref);
        }
      if(ev) RegisterSweep(li, i);
     }
  }

void RegisterSweep(int li, int s)
  {
   g_lv[li].used = true;
   bool sh = g_lv[li].hi;
   SetBias(g_lv[li].tf, sh, g_lv[li].px);
   // leg origin: lowest low (short) between the previous 5m swing high (2 each side, before the sweep extreme) and the extreme
   int a0 = IMax(s - 3, g5base), ext0 = a0;
   for(int m = a0; m <= s; m++) if(sh ? H5(m) > H5(ext0) : L5(m) < L5(ext0)) ext0 = m;
   int ph = -1;
   for(int m = ext0 - 3; m >= IMax(g5base + 2, ext0 - 2000); m--)
     {
      bool pv = true;
      for(int q = m - 2; q <= m + 2 && pv; q++) if(sh ? H5(q) > H5(m) : L5(q) < L5(m)) pv = false;
      if(pv) { ph = m; break; }
     }
   if(ph < 0) return;
   int origin = ph;
   for(int m = ph; m <= ext0; m++) if(sh ? L5(m) < L5(origin) : H5(m) > H5(origin)) origin = m;
   // the FVG to invert: intact bullish (short) 5m or 15m FVG nearest below the sweep, completed in the lookback before it
   int want = sh ? 1 : -1;
   bool found = false; double bTop = 0, bBot = 0; int bIdx = -1; bool b15 = false;
   for(int pass = 0; pass < 2; pass++)
     {
      int nz = pass == 0 ? ArraySize(g_f5) : ArraySize(g_f15);
      for(int z = 0; z < nz; z++)
        {
         Zn f;
         if(pass == 0) f = g_f5[z]; else f = g_f15[z];
         if(f.dir != want || f.idx >= s || f.idx < s - InpIfvgLookback || f.idx < g5base) continue;
         bool intact = true;
         for(int m = f.idx + 1; m <= s - 1 && intact; m++) if(sh ? C5(m) < f.bot : C5(m) > f.top) intact = false;
         if(!intact) continue;
         if(!found || (sh ? f.bot > bBot : f.top < bTop)) { found = true; bTop = f.top; bBot = f.bot; bIdx = f.idx; b15 = f.m15; }
        }
     }
   if(!found) return;
   int n = ArraySize(g_sw); ArrayResize(g_sw, n + 1, 64);
   g_sw[n].sh = sh; g_sw[n].s = s; g_sw[n].origin = origin; g_sw[n].olv = sh ? L5(origin) : H5(origin);
   g_sw[n].fTop = bTop; g_sw[n].fBot = bBot; g_sw[n].fIdx = bIdx; g_sw[n].f15 = b15;
   g_sw[n].ex = s; g_sw[n].msI = -1; g_sw[n].inv = false; g_sw[n].brk = -1; g_sw[n].tf = g_lv[li].tf; g_sw[n].px = g_lv[li].px;
  }

void RemoveSw(int k)
  {
   int n = ArraySize(g_sw);
   for(int m = k; m < n - 1; m++) g_sw[m] = g_sw[m + 1];
   ArrayResize(g_sw, n - 1);
  }

bool Displacement(int t, bool sh)
  {
   int k = t;
   while(k >= g5base && (sh ? C5(k) < O5(k) : C5(k) > O5(k))) k--;
   int run = t - k;
   double move = run > 0 ? MathAbs(C5(t) - O5(k + 1)) : 0;
   if(run >= InpDispCandles && move >= InpDispATR * A5(t)) return true;
   double body = sh ? O5(t) - C5(t) : C5(t) - O5(t);
   return body >= InpDispATR * A5(t);
  }

//+------------------------------------------------------------------+
//| Rules 3-4: within InpReversal candles of the sweep, a 5m close     |
//| through the FVG (IFVG) AND a break of the leg-origin low (or the   |
//| post-sweep MSS low); the completing candle needs displacement.     |
//+------------------------------------------------------------------+
void ProgressSweeps(int t)
  {
   for(int k = ArraySize(g_sw) - 1; k >= 0; k--)
     {
      if(t > g_sw[k].s + InpReversal) { RemoveSw(k); continue; }
      bool sh = g_sw[k].sh;
      if(sh ? H5(t) > H5(g_sw[k].ex) : L5(t) < L5(g_sw[k].ex)) { g_sw[k].ex = t; g_sw[k].msI = -1; }
      int m = t - 3;                                           // 5m swing (2 each side) confirmed by the previous candle
      if(InpMssBreak && m > g_sw[k].ex && m - 2 >= g5base)
        {
         bool pv = true;
         for(int q = m - 2; q <= m + 2 && pv; q++) if(sh ? L5(q) < L5(m) : H5(q) > H5(m)) pv = false;
         if(pv) g_sw[k].msI = m;
        }
      if(sh ? C5(t) < g_sw[k].fBot : C5(t) > g_sw[k].fTop) g_sw[k].inv = true;
      if(g_sw[k].brk < 0)
        {
         double bx = InpBosWick ? (sh ? L5(t) : H5(t)) : C5(t);
         if(sh ? bx < g_sw[k].olv : bx > g_sw[k].olv) g_sw[k].brk = g_sw[k].origin;
         else if(g_sw[k].msI >= 0 && (sh ? bx < L5(g_sw[k].msI) : bx > H5(g_sw[k].msI))) g_sw[k].brk = g_sw[k].msI;
        }
      if(g_sw[k].inv && g_sw[k].brk >= 0)
        {
         if(Displacement(t, sh)) CreateSetup(k, t);
         RemoveSw(k);
        }
     }
  }

void CreateSetup(int k, int j)
  {
   bool sh = g_sw[k].sh;
   int brk = g_sw[k].brk;
   // the 5m breaker: last bearish (short) candle at or before the low that was broken (10 candles) -> stop = its high
   int ob = -1;
   for(int m = brk; m >= IMax(brk - 9, g5base); m--) if(sh ? C5(m) < O5(m) : C5(m) > O5(m)) { ob = m; break; }
   if(ob < 0) return;
   double stop = sh ? H5(ob) : L5(ob);
   if(InpBiasFilter && g_bias != (sh ? -1 : 1)) return;
   for(int q = 0; q < ArraySize(g_sg); q++)                    // same IFVG + same reversal candle from another level: once
      if(g_sg[q].sh == sh && g_sg[q].fIdx == g_sw[k].fIdx && g_sg[q].f15 == g_sw[k].f15 && g_sg[q].j == j) return;
   int a0 = IMax(g_sw[k].s - 3, g5base), ext = a0;            // the sweep extreme
   for(int m = a0; m <= j; m++) if(sh ? H5(m) > H5(ext) : L5(m) < L5(ext)) ext = m;

   int n = ArraySize(g_sg); ArrayResize(g_sg, n + 1, 256);
   g_sg[n].sh = sh; g_sg[n].j = j; g_sg[n].revClose = T5(j) + 300;
   g_sg[n].expiry = g_sg[n].revClose + InpEntryValidMin * 60;
   g_sg[n].stop = stop; g_sg[n].ext = ext; g_sg[n].fIdx = g_sw[k].fIdx; g_sg[n].f15 = g_sw[k].f15;
   g_sg[n].zTop = 0; g_sg[n].zBot = 0; g_sg[n].zIdx = -1; g_sg[n].zVI = false; g_sg[n].level = 0; g_sg[n].liveFrom = -1;
   g_sg[n].state = 0; g_sg[n].entry = 0; g_sg[n].tp = 0; g_sg[n].vstop = 0; g_sg[n].risk = 0; g_sg[n].be = false;
   g_sg[n].tp1 = 0; g_sg[n].tp2 = 0; g_sg[n].halfIdx = -1;
   g_sg[n].fillIdx = -1; g_sg[n].ticket = 0; g_sg[n].want = false;
   g_sg[n].id = (sh ? "ICTi S " : "ICTi L ") + TimeToString(T5(j), TIME_DATE | TIME_MINUTES);
   g_sg[n].info = TFN[g_sw[k].tf] + (sh ? " H " : " L ") + DoubleToString(g_sw[k].px, _Digits) + " swept " +
                  TimeToString(T5(g_sw[k].s), TIME_DATE | TIME_MINUTES) + " | " + (g_sw[k].f15 ? "15m" : "5m") + " IFVG + 5m " +
                  (brk == g_sw[k].origin ? "BOS" : "MSS") + " @ " + DoubleToString(sh ? L5(brk) : H5(brk), _Digits) +
                  " | stop (breaker) " + DoubleToString(stop, _Digits);
   Notify((sh ? "SHORT" : "LONG") + string(" setup: ") + g_sg[n].info);
  }

//+------------------------------------------------------------------+
//| Rule 5: entry zone = the latest bearish (short) 5m FVG or volume   |
//| imbalance of the drop from the sweep extreme, completed up to      |
//| InpFvgAfter candles after the reversal (FVG preferred on a tie).   |
//| Limit at its near edge (bottom for a short), live from the next    |
//| candle. A newer zone replaces the order while it is not filled.    |
//+------------------------------------------------------------------+
void RefineSignals(int i)
  {
   for(int k = 0; k < ArraySize(g_sg); k++)
     {
      if(g_sg[k].state > 1 || g_sg[k].fillIdx >= 0 || i > g_sg[k].j + InpFvgAfter) continue;
      bool sh = g_sg[k].sh;
      int want = sh ? -1 : 1, lim = IMin(i, g_sg[k].j + InpFvgAfter);
      int bi = -1; bool bvi = false; double bt = 0, bb = 0;
      for(int z = 0; z < ArraySize(g_f5); z++)
         if(g_f5[z].dir == want && g_f5[z].start >= g_sg[k].ext && g_f5[z].idx <= lim && g_f5[z].idx > bi)
           { bi = g_f5[z].idx; bvi = false; bt = g_f5[z].top; bb = g_f5[z].bot; }
      for(int z = 0; z < ArraySize(g_vi); z++)
         if(g_vi[z].dir == want && g_vi[z].start >= g_sg[k].ext && g_vi[z].idx <= lim && g_vi[z].idx > bi)
           { bi = g_vi[z].idx; bvi = true; bt = g_vi[z].top; bb = g_vi[z].bot; }
      if(bi < 0)
        {
         if(i >= g_sg[k].j + InpFvgAfter) { g_sg[k].state = 3; }
         continue;
        }
      if(bi == g_sg[k].zIdx && bvi == g_sg[k].zVI && bt == g_sg[k].zTop && bb == g_sg[k].zBot) continue;
      double level = sh ? bb : bt;
      if(sh ? g_sg[k].stop <= level : g_sg[k].stop >= level) { DropSignal(k, "stop not beyond the entry zone"); continue; }
      if(InpOnePerEntry)
        {
         bool dup = false;
         for(int q = 0; q < ArraySize(g_sg) && !dup; q++)
            if(q != k && g_sg[q].sh == sh && g_sg[q].zTop == bt && g_sg[q].zBot == bb &&
               (g_sg[q].state == 1 || g_sg[q].state == 2 || g_sg[q].fillIdx >= 0)) dup = true;
         if(dup) { DropSignal(k, "duplicate entry (one trade per entry)"); continue; }
        }
      g_sg[k].zIdx = bi; g_sg[k].zVI = bvi; g_sg[k].zTop = bt; g_sg[k].zBot = bb; g_sg[k].level = level;
      g_sg[k].liveFrom = IMax(g_sg[k].j, bi) + 1;
      g_sg[k].state = 1;
      if(g_live)
        {
         Notify((sh ? "SELL LIMIT " : "BUY LIMIT ") + DoubleToString(level, _Digits) + " | SL " + DoubleToString(g_sg[k].stop, _Digits) +
                " | entry " + (bvi ? "5m VI " : "5m FVG ") + DoubleToString(bb, _Digits) + "-" + DoubleToString(bt, _Digits) +
                " valid until " + TimeToString(g_sg[k].expiry, TIME_DATE | TIME_MINUTES) + " | " + g_sg[k].info);
         g_sg[k].want = true;
         PlaceReal(k);
        }
     }
  }

void DropSignal(int k, string why)
  {
   if(g_sg[k].want) CancelReal(k);
   g_sg[k].state = 3;
   g_sg[k].want = false;
   if(g_live) Print("Setup ", g_sg[k].id, " dropped: ", why);
  }

double MajorSwing(int q, bool sh, double entry)     // nearest major 5m swing (10 each side) beyond the entry, confirmed by candle q-1
  {
   const int p = 10;
   double best = 0; bool got = false;
   for(int i = q - 1 - p; i >= IMax(g5base + p, q - 1 - 2000); i--)
     {
      double v = sh ? L5(i) : H5(i);
      if(sh ? v >= entry : v <= entry) continue;
      bool pv = true;
      for(int k = i - p; k <= i + p && pv; k++) if(sh ? L5(k) < v : H5(k) > v) pv = false;
      if(!pv) continue;
      if(!got || (sh ? v > best : v < best)) { best = v; got = true; }
     }
   return got ? best : 0;
  }

//+------------------------------------------------------------------+
//| runner target: the nearest Rule 1 swing (D / W / M / 4H / 1H)      |
//| low (short) below `beyond` / high (long) above it that is          |
//| confirmed and not swept yet. 0 = none.                             |
//+------------------------------------------------------------------+
double Runner(bool sh, double beyond, string &tx)
  {
   datetime now = g5cnt > 0 ? T5(N5() - 1) + 300 : TimeCurrent();
   double best = 0; bool got = false; tx = "";
   for(int li = 0; li < ArraySize(g_lv); li++)
     {
      if(g_lv[li].used || g_lv[li].tf > 4 || g_lv[li].hi == sh || g_lv[li].ct > now) continue;   // short -> swing lows
      double v = g_lv[li].px;
      if(sh ? v >= beyond : v <= beyond) continue;
      if(!got || (sh ? v > best : v < best)) { best = v; got = true; tx = TFN[g_lv[li].tf] + " swing"; }
     }
   return got ? best : 0;
  }

//+------------------------------------------------------------------+
//| the model's own fills / exits on completed candles (as the         |
//| backtest): used for one-per-entry, refinement and the statistics.  |
//| Real orders are filled and closed by the broker.                   |
//+------------------------------------------------------------------+
void SignalsModel(int i)
  {
   for(int k = 0; k < ArraySize(g_sg); k++)
     {
      bool sh = g_sg[k].sh;
      if(g_sg[k].state == 1 && i >= g_sg[k].liveFrom)
        {
         if(T5(i) >= g_sg[k].expiry) { DropSignal(k, "expired"); continue; }
         if(InEOD(T5(i))) { DropSignal(k, "end of day - no entries before the market close"); continue; }
         if(sh ? O5(i) > g_sg[k].stop : O5(i) < g_sg[k].stop) { DropSignal(k, "a candle opened beyond the stop"); continue; }
         if(sh ? H5(i) >= g_sg[k].level : L5(i) <= g_sg[k].level)
           {
            double e = sh ? MathMax(g_sg[k].level, O5(i)) : MathMin(g_sg[k].level, O5(i));
            if(sh ? g_sg[k].stop <= e : g_sg[k].stop >= e) { DropSignal(k, "no stop beyond the fill"); continue; }
            double risk = MathAbs(e - g_sg[k].stop);
            double tp = sh ? e - InpTargetR * risk : e + InpTargetR * risk;
            g_sg[k].tp1 = tp; g_sg[k].tp2 = 0; g_sg[k].halfIdx = -1;
            if(InpPartial) { string tx; g_sg[k].tp2 = Runner(sh, tp, tx); if(g_sg[k].tp2 > 0) tp = g_sg[k].tp2; }
            else if(InpTargetSwing) { double sw = MajorSwing(i, sh, e); if(sw > 0) tp = sw; }
            g_sg[k].entry = e; g_sg[k].risk = risk; g_sg[k].tp = tp; g_sg[k].vstop = g_sg[k].stop; g_sg[k].be = false;
            g_sg[k].fillIdx = i; g_sg[k].state = 2;
            if(sh ? H5(i) >= g_sg[k].vstop : L5(i) <= g_sg[k].vstop) { ModelExit(k, g_sg[k].vstop, "stop"); continue; }
           }
         continue;
        }
      if(g_sg[k].state == 2 && i > g_sg[k].fillIdx)
        {
         bool half = g_sg[k].halfIdx >= 0, part = InpPartial && g_sg[k].tp2 > 0;
         if(sh ? H5(i) >= g_sg[k].vstop : L5(i) <= g_sg[k].vstop)
           { ModelExit(k, g_sg[k].vstop, half ? "TP1 + breakeven" : g_sg[k].be ? "breakeven" : "stop"); continue; }
         if(part && !half)
           {
            if(sh ? L5(i) <= g_sg[k].tp1 : H5(i) >= g_sg[k].tp1)          // first part closed, the rest at breakeven
              { g_sg[k].halfIdx = i; g_sg[k].vstop = g_sg[k].entry; g_sg[k].be = true; continue; }
           }
         else if((!part || i > g_sg[k].halfIdx) && (sh ? L5(i) <= g_sg[k].tp : H5(i) >= g_sg[k].tp))
           { ModelExit(k, g_sg[k].tp, half ? "TP1 + TP2" : "target"); continue; }
         if(EODCandle(T5(i)))                                             // end of day: the rest closes at this candle's close
           { ModelExit(k, C5(i), g_sg[k].halfIdx >= 0 ? "TP1 + end of day" : "end of day"); continue; }
         if(InpBE_at_R > 0 && !g_sg[k].be && (!InpPartial || InpBEBeforeTP1) &&
            (sh ? L5(i) <= g_sg[k].entry - InpBE_at_R * g_sg[k].risk : H5(i) >= g_sg[k].entry + InpBE_at_R * g_sg[k].risk))
           { g_sg[k].vstop = g_sg[k].entry; g_sg[k].be = true; }
        }
     }
  }

void ModelExit(int k, double px, string why)
  {
   double mv = g_sg[k].sh ? g_sg[k].entry - px : px - g_sg[k].entry;
   if(g_sg[k].halfIdx >= 0)                                          // size-weighted: first part at tp1 + the rest at px
     {
      double w = InpPartialPct / 100.0;
      mv = w * (g_sg[k].sh ? g_sg[k].entry - g_sg[k].tp1 : g_sg[k].tp1 - g_sg[k].entry) + (1 - w) * mv;
     }
   double r = mv / g_sg[k].risk;
   g_sg[k].state = 3;
   g_vTrades++; g_vR += r; if(r > 0.05) g_vWins++;
   if(g_live) Print("Model trade ", g_sg[k].id, " closed: ", why, " ", DoubleToString(r, 2), "R (before costs)");
  }

//+------------------------------------------------------------------+
//| housekeeping                                                      |
//+------------------------------------------------------------------+
void TrimD(double &a[], int shift, int cnt)   { double tmp[]; ArrayResize(tmp, cnt); ArrayCopy(tmp, a, 0, shift, cnt); ArrayCopy(a, tmp, 0, 0, cnt); }
void TrimT(datetime &a[], int shift, int cnt) { datetime tmp[]; ArrayResize(tmp, cnt); ArrayCopy(tmp, a, 0, shift, cnt); ArrayCopy(a, tmp, 0, 0, cnt); }

void PruneZ(Zn &a[], int minIdx)
  {
   int n = ArraySize(a), w = 0;
   for(int r = 0; r < n; r++) if(a[r].idx >= minIdx) { if(w != r) a[w] = a[r]; w++; }
   ArrayResize(a, w);
  }

void CompactLevels()                         // drop swept / expired levels
  {
   int n = ArraySize(g_lv), w = 0;
   for(int r = 0; r < n; r++) if(!g_lv[r].used) { if(w != r) g_lv[w] = g_lv[r]; w++; }
   ArrayResize(g_lv, w);
  }

void Compact()
  {
   CompactLevels();
   int n = 0, w = 0;
   // setups: keep the last 3000 candles (one-per-entry memory)
   int now = N5() - 1;
   n = ArraySize(g_sg); w = 0;
   for(int r = 0; r < n; r++)
      if(g_sg[r].state != 3 || g_sg[r].j >= now - 3000) { if(w != r) g_sg[w] = g_sg[r]; w++; }
   ArrayResize(g_sg, w);
   // 5m buffer: keep the last 5000 candles
   if(g5cnt > 9000)
     {
      int shift = g5cnt - 5000;
      TrimD(g5o, shift, 5000); TrimD(g5h, shift, 5000); TrimD(g5l, shift, 5000); TrimD(g5c, shift, 5000);
      TrimD(g5tr, shift, 5000); TrimD(g5atr, shift, 5000); TrimT(g5t, shift, 5000);
      g5base += shift; g5cnt = 5000;
     }
   PruneZ(g_f5, g5base + 10); PruneZ(g_f15, g5base + 10); PruneZ(g_vi, g5base + 10);
   int nq = ArraySize(g_q15h);
   if(nq > 2000) { TrimD(g_q15h, nq - 100, 100); TrimD(g_q15l, nq - 100, 100); ArrayResize(g_q15h, 100); ArrayResize(g_q15l, 100); }
  }

//+------------------------------------------------------------------+
//| real orders                                                        |
//+------------------------------------------------------------------+
ulong FindPending(string cmt)
  {
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      ulong tk = OrderGetTicket(i);
      if(tk == 0) continue;
      if(OrderGetInteger(ORDER_MAGIC) == (long)InpMagic && OrderGetString(ORDER_SYMBOL) == g_sym && OrderGetString(ORDER_COMMENT) == cmt) return tk;
     }
   return 0;
  }

int CountOurs()
  {
   int n = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong tk = PositionGetTicket(i);
      if(tk == 0) continue;
      if(PositionGetInteger(POSITION_MAGIC) == (long)InpMagic && PositionGetString(POSITION_SYMBOL) == g_sym) n++;
     }
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      ulong tk = OrderGetTicket(i);
      if(tk == 0) continue;
      if(OrderGetInteger(ORDER_MAGIC) == (long)InpMagic && OrderGetString(ORDER_SYMBOL) == g_sym) n++;
     }
   return n;
  }

double LotsForRisk(double entry, double stop)
  {
   double riskMoney = AccountInfoDouble(ACCOUNT_BALANCE) * InpRiskPct / 100.0;
   double tickVal  = SymbolInfoDouble(g_sym, SYMBOL_TRADE_TICK_VALUE);
   double tickSize = SymbolInfoDouble(g_sym, SYMBOL_TRADE_TICK_SIZE);
   double stepLot  = SymbolInfoDouble(g_sym, SYMBOL_VOLUME_STEP);
   double minLot   = SymbolInfoDouble(g_sym, SYMBOL_VOLUME_MIN);
   double maxLot   = SymbolInfoDouble(g_sym, SYMBOL_VOLUME_MAX);
   double dist = MathAbs(entry - stop);
   if(dist <= 0 || tickVal <= 0 || tickSize <= 0 || stepLot <= 0) return 0;
   double lots = riskMoney / ((dist / tickSize) * tickVal);
   lots = MathFloor(lots / stepLot) * stepLot;
   if(lots < minLot) { Print("Risk budget below the minimum lot (", DoubleToString(minLot, 2), ") - order skipped."); return 0; }
   return MathMin(maxLot, lots);
  }

void PlaceReal(int k)
  {
   if(!LiveAllowed() || g_halted || !g_sg[k].want || g_sg[k].state != 1) return;
   if(InEOD(TimeCurrent())) return;                                      // no entries in the last minutes before the close
   if(g_sg[k].ticket > 0)
     {
      if(OrderSelect(g_sg[k].ticket)) { trade.OrderDelete(g_sg[k].ticket); g_sg[k].ticket = 0; }   // replace (newer entry zone)
      else { g_sg[k].want = false; return; }                                                        // already filled / gone
     }
   if(InpMaxOpen > 0 && CountOurs() >= InpMaxOpen) { Print("Max open orders/positions reached - ", g_sg[k].id, " not placed."); return; }
   if(!g_hedging && CountOurs() > 0)                { Print("Netting account: a trade is already open - ", g_sg[k].id, " not placed."); return; }
   bool sh = g_sg[k].sh;
   double bid = SymbolInfoDouble(g_sym, SYMBOL_BID), ask = SymbolInfoDouble(g_sym, SYMBOL_ASK);
   if(InpMaxSpread > 0 && ask - bid > InpMaxSpread) { Print("Spread ", DoubleToString(ask - bid, _Digits), " too wide - retry next candle."); return; }
   double fo = iOpen(g_sym, PERIOD_M5, 0);
   if(fo > 0 && (sh ? fo > g_sg[k].stop : fo < g_sg[k].stop)) return;   // the model cancels this setup on this candle

   int dg = (int)SymbolInfoInteger(g_sym, SYMBOL_DIGITS);
   double e = NormalizeDouble(g_sg[k].level, dg), s = NormalizeDouble(g_sg[k].stop, dg);
   double minDist = (double)SymbolInfoInteger(g_sym, SYMBOL_TRADE_STOPS_LEVEL) * g_point;
   bool limitOK = sh ? (e >= bid + minDist) : (e <= ask - minDist);
   bool mkt = false;
   if(!limitOK)
     {
      double px = sh ? bid : ask;                       // price already at / through the entry: the model fills here
      if(!(sh ? px >= e : px <= e)) { Print("Entry too close to the market for a limit - ", g_sg[k].id, " skipped."); return; }
      e = px; mkt = true;
     }
   if(sh ? s <= e + minDist : s >= e - minDist) { Print("Stop not beyond the entry - ", g_sg[k].id, " skipped."); g_sg[k].want = false; return; }
   double risk = MathAbs(e - s);
   double t = sh ? e - InpTargetR * risk : e + InpTargetR * risk;
   string rtx = "";
   if(InpPartial) { double r2 = Runner(sh, t, rtx); if(r2 > 0) t = r2; }   // broker TP = the runner; the EA closes the first part
   else if(InpTargetSwing) { double sw = MajorSwing(N5(), sh, e); if(sw > 0) t = sw; }
   t = NormalizeDouble(t, dg);
   double lots = LotsForRisk(e, s);
   if(lots <= 0) { g_sg[k].want = false; return; }
   double margin = 0;
   if(OrderCalcMargin(sh ? ORDER_TYPE_SELL : ORDER_TYPE_BUY, g_sym, lots, e, margin) && margin > AccountInfoDouble(ACCOUNT_MARGIN_FREE) * 0.9)
     { Print("Not enough free margin for ", DoubleToString(lots, 2), " lots - skipped."); return; }

   trade.SetExpertMagicNumber(InpMagic);
   string cmt = g_sg[k].id;
   bool ok;
   if(mkt) ok = sh ? trade.Sell(lots, g_sym, 0, s, t, cmt) : trade.Buy(lots, g_sym, 0, s, t, cmt);
   else
     {
      ok = sh ? trade.SellLimit(lots, e, g_sym, s, t, ORDER_TIME_SPECIFIED, g_sg[k].expiry, cmt)
              : trade.BuyLimit(lots, e, g_sym, s, t, ORDER_TIME_SPECIFIED, g_sg[k].expiry, cmt);
      if(!ok && trade.ResultRetcode() == TRADE_RETCODE_INVALID_EXPIRATION)       // no expiry support: GTC, the EA cancels it
         ok = sh ? trade.SellLimit(lots, e, g_sym, s, t, ORDER_TIME_GTC, 0, cmt)
                 : trade.BuyLimit(lots, e, g_sym, s, t, ORDER_TIME_GTC, 0, cmt);
     }
   if(ok)
     {
      g_sg[k].ticket = trade.ResultOrder();
      if(mkt) g_sg[k].want = false;
      Print("Order placed: ", mkt ? "MARKET " : "LIMIT ", (sh ? "SELL " : "BUY "), DoubleToString(lots, 2), " @ ", DoubleToString(e, dg),
            " SL ", DoubleToString(s, dg), " TP ", DoubleToString(t, dg),
            (InpPartial ? (rtx != "" ? " (" + rtx + "), " + DoubleToString(InpPartialPct, 0) + "% at " + DoubleToString(InpTargetR, 1) + "R"
                                     : " (no Rule 1 swing beyond " + DoubleToString(InpTargetR, 1) + "R: everything there)") : ""), " | ", cmt);
     }
   else Print("Order failed (retry next candle): ", trade.ResultRetcode(), " ", trade.ResultRetcodeDescription());
  }

void CancelReal(int k)
  {
   if(g_sg[k].ticket > 0 && OrderSelect(g_sg[k].ticket))
     {
      if(trade.OrderDelete(g_sg[k].ticket)) Print("Order cancelled: ", g_sg[k].id);
     }
   g_sg[k].want = false;
  }

// at every new 5m candle: retry orders that could not be placed, cancel orders whose candle opened beyond the stop,
// breakeven on open positions (judged on the candle that just closed, from the candle after the fill)
void NewBarMaintenance()
  {
   double fo = iOpen(g_sym, PERIOD_M5, 0);
   for(int k = 0; k < ArraySize(g_sg); k++)
     {
      if(!g_sg[k].want) continue;
      if(g_sg[k].state != 1) { if(g_sg[k].state == 3) CancelReal(k); continue; }
      if(g_sg[k].ticket > 0 && fo > 0 && (g_sg[k].sh ? fo > g_sg[k].stop : fo < g_sg[k].stop)) { CancelReal(k); continue; }
      if(g_sg[k].ticket == 0 && !g_halted) PlaceReal(k);
     }
   if(InpBE_at_R <= 0 || g5cnt == 0 || (InpPartial && !InpBEBeforeTP1)) return;
   int i = N5() - 1;
   for(int n = PositionsTotal() - 1; n >= 0; n--)
     {
      ulong tk = PositionGetTicket(n);
      if(!PositionSelectByTicket(tk)) continue;
      if(PositionGetInteger(POSITION_MAGIC) != (long)InpMagic || PositionGetString(POSITION_SYMBOL) != g_sym) continue;
      bool   isBuy = PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY;
      double open  = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl    = PositionGetDouble(POSITION_SL);
      double tp    = PositionGetDouble(POSITION_TP);
      datetime ot  = (datetime)PositionGetInteger(POSITION_TIME);
      if(sl <= 0 || ot >= T5(i)) continue;                                    // the fill candle itself does not count
      if(isBuy ? sl >= open - 1e-9 : sl <= open + 1e-9) continue;            // already at breakeven
      double risk = MathAbs(open - sl);
      bool reached = isBuy ? H5(i) >= open + InpBE_at_R * risk : L5(i) <= open - InpBE_at_R * risk;
      if(!reached) continue;
      double bid = SymbolInfoDouble(g_sym, SYMBOL_BID), ask = SymbolInfoDouble(g_sym, SYMBOL_ASK);
      double minDist = (double)SymbolInfoInteger(g_sym, SYMBOL_TRADE_STOPS_LEVEL) * g_point;
      bool valid = isBuy ? open < bid - minDist : open > ask + minDist;
      if(valid) { if(trade.PositionModify(tk, open, tp)) Print("Stop moved to breakeven ", DoubleToString(open, _Digits)); }
      else      { if(trade.PositionClose(tk)) Print("Breakeven level already passed - position closed at market."); }
     }
  }

//+------------------------------------------------------------------+
//| partial close (every tick): when price reaches the first target    |
//| (entry +/- InpTargetR x the initial stop distance) close           |
//| InpPartialPct of the position and move the stop to breakeven; the  |
//| rest keeps its broker TP (the runner swing). The first target is   |
//| stored per position in a terminal global variable (survives a      |
//| restart). A position whose TP already is the first target (no      |
//| runner swing) is left to the broker.                               |
//+------------------------------------------------------------------+
void ManagePartial()
  {
   if(!InpPartial) return;
   double bid = SymbolInfoDouble(g_sym, SYMBOL_BID), ask = SymbolInfoDouble(g_sym, SYMBOL_ASK);
   double stepLot = SymbolInfoDouble(g_sym, SYMBOL_VOLUME_STEP), minLot = SymbolInfoDouble(g_sym, SYMBOL_VOLUME_MIN);
   double minDist = (double)SymbolInfoInteger(g_sym, SYMBOL_TRADE_STOPS_LEVEL) * g_point;
   for(int n = PositionsTotal() - 1; n >= 0; n--)
     {
      ulong tk = PositionGetTicket(n);
      if(!PositionSelectByTicket(tk)) continue;
      if(PositionGetInteger(POSITION_MAGIC) != (long)InpMagic || PositionGetString(POSITION_SYMBOL) != g_sym) continue;
      bool   isBuy = PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY;
      double open = PositionGetDouble(POSITION_PRICE_OPEN), sl = PositionGetDouble(POSITION_SL), tp = PositionGetDouble(POSITION_TP);
      double vol  = PositionGetDouble(POSITION_VOLUME);
      string gv = "ICTINTRA_TP1_" + IntegerToString((long)tk);
      if(!GlobalVariableCheck(gv))
        {
         double risk = MathAbs(open - sl);
         if(sl <= 0 || risk <= 0) continue;
         double t1 = isBuy ? open + InpTargetR * risk : open - InpTargetR * risk;
         bool noRunner = tp <= 0 || MathAbs(tp - t1) <= 2 * g_point || (isBuy ? tp < t1 : tp > t1);
         GlobalVariableSet(gv, noRunner ? 0 : t1);
        }
      double tp1 = GlobalVariableGet(gv);
      if(tp1 <= 0) continue;                                             // done, or no runner (broker TP = first target)
      if(isBuy ? bid < tp1 : ask > tp1) continue;
      int dg = (int)SymbolInfoInteger(g_sym, SYMBOL_DIGITS);
      double part = stepLot > 0 ? MathFloor(vol * InpPartialPct / 100.0 / stepLot + 1e-9) * stepLot : vol;
      if(part < minLot - 1e-9 || vol - part < minLot - 1e-9)
        {
         if(trade.PositionClose(tk)) { GlobalVariableSet(gv, 0); Notify("First target " + DoubleToString(tp1, dg) + ": volume too small to split - position closed."); }
         continue;
        }
      if(!trade.PositionClosePartial(tk, part)) { Print("Partial close failed: ", trade.ResultRetcode(), " ", trade.ResultRetcodeDescription()); continue; }
      GlobalVariableSet(gv, 0);
      bool valid = isBuy ? open < bid - minDist : open > ask + minDist;
      if(valid && PositionSelectByTicket(tk)) trade.PositionModify(tk, open, tp);
      else if(!valid && PositionSelectByTicket(tk)) trade.PositionClose(tk);       // breakeven already passed: close the rest
      Notify(DoubleToString(part, 2) + " lots closed at the first target " + DoubleToString(tp1, dg) + " - stop to breakeven " +
             DoubleToString(open, dg) + ", rest to " + DoubleToString(tp, dg));
     }
  }

//+------------------------------------------------------------------+
//| end of day: close every position of this EA at market and cancel  |
//| its pending orders (from close - InpEODMin to the close)           |
//+------------------------------------------------------------------+
void FlattenEOD()
  {
   int closed = 0, cancelled = 0;
   for(int n = PositionsTotal() - 1; n >= 0; n--)
     {
      ulong tk = PositionGetTicket(n);
      if(tk == 0 || !PositionSelectByTicket(tk)) continue;
      if(PositionGetInteger(POSITION_MAGIC) != (long)InpMagic || PositionGetString(POSITION_SYMBOL) != g_sym) continue;
      if(trade.PositionClose(tk)) closed++;
      else Print("End-of-day close failed: ", trade.ResultRetcode(), " ", trade.ResultRetcodeDescription());
     }
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      ulong tk = OrderGetTicket(i);
      if(tk == 0) continue;
      if(OrderGetInteger(ORDER_MAGIC) == (long)InpMagic && OrderGetString(ORDER_SYMBOL) == g_sym && trade.OrderDelete(tk)) cancelled++;
     }
   for(int k = 0; k < ArraySize(g_sg); k++) if(g_sg[k].state == 1) { g_sg[k].want = false; g_sg[k].ticket = 0; }
   long day = NYL(TimeCurrent()) / 86400;
   if((closed > 0 || cancelled > 0) || day != g_eodDay)
     {
      if(closed > 0 || cancelled > 0)
         Notify("End of day (" + IntegerToString(InpEODMin) + " min before the " + InpEODCloseNY + " NY close): " + IntegerToString(closed) +
                " position(s) closed, " + IntegerToString(cancelled) + " pending order(s) cancelled.");
      g_eodDay = day;
     }
  }

void OnTradeTransaction(const MqlTradeTransaction &tr, const MqlTradeRequest &rq, const MqlTradeResult &rs)
  {
   if(tr.type != TRADE_TRANSACTION_DEAL_ADD) return;
   if(!HistoryDealSelect(tr.deal)) return;
   if(HistoryDealGetInteger(tr.deal, DEAL_MAGIC) != (long)InpMagic || HistoryDealGetString(tr.deal, DEAL_SYMBOL) != g_sym) return;
   long entry = HistoryDealGetInteger(tr.deal, DEAL_ENTRY);
   double px = HistoryDealGetDouble(tr.deal, DEAL_PRICE);
   if(entry == DEAL_ENTRY_IN) Notify("FILLED " + HistoryDealGetString(tr.deal, DEAL_COMMENT) + " @ " + DoubleToString(px, _Digits));
   else if(entry == DEAL_ENTRY_OUT)
      Notify("CLOSED @ " + DoubleToString(px, _Digits) + " profit " + DoubleToString(HistoryDealGetDouble(tr.deal, DEAL_PROFIT), 2));
  }

//+------------------------------------------------------------------+
//| loss limits                                                       |
//+------------------------------------------------------------------+
bool RiskHalted()
  {
   double eq = AccountInfoDouble(ACCOUNT_EQUITY);
   MqlDateTime d; TimeToStruct(TimeCurrent(), d);
   int key = d.year * 10000 + d.mon * 100 + d.day;
   if(key != g_dayKey || g_dayStartEq <= 0)
     {
      g_dayKey = key; g_dayStartEq = eq; g_haltedDay = false;
      GlobalVariableSet(g_gvDayKey, key); GlobalVariableSet(g_gvDayEq, eq);
     }
   if(eq > g_peakEq) { g_peakEq = eq; GlobalVariableSet(g_gvPeak, g_peakEq); }
   if(InpDailyLossPct > 0 && !g_haltedDay && eq <= g_dayStartEq * (1.0 - InpDailyLossPct / 100.0))
     { g_haltedDay = true; Print("DAILY LOSS LIMIT hit - no new trades today."); }
   if(InpMaxDrawdownPct > 0 && !g_haltedDD && eq <= g_peakEq * (1.0 - InpMaxDrawdownPct / 100.0))
     { g_haltedDD = true; Print("MAX DRAWDOWN LIMIT hit - EA halted. Set InpResetPeak=true for one restart to resume."); }
   return g_haltedDay || g_haltedDD;
  }

void HandleHalt()
  {
   for(int k = 0; k < ArraySize(g_sg); k++) if(g_sg[k].want) CancelReal(k);
   if(InpFlattenOnLimit)
      for(int i = PositionsTotal() - 1; i >= 0; i--)
        {
         ulong tk = PositionGetTicket(i);
         if(tk == 0) continue;
         if(PositionGetInteger(POSITION_MAGIC) == (long)InpMagic && PositionGetString(POSITION_SYMBOL) == g_sym) trade.PositionClose(tk);
        }
  }

void ShowStatus()
  {
   int alive = 0, pend = 0, open = 0;
   for(int i = 0; i < ArraySize(g_lv); i++) if(!g_lv[i].used) alive++;
   for(int k = 0; k < ArraySize(g_sg); k++) { if(g_sg[k].state == 1) pend++; if(g_sg[k].state == 2) open++; }
   Comment("ICT Intraday EA  |  ", LiveAllowed() ? "AUTOMATIC" : "SIGNALS ONLY", g_halted ? "  |  HALTED (loss limit)" : "",
           "\nBias: ", g_biasTx,
           "\nLive Rule 1 levels: ", alive, "   swept levels waiting for IFVG + break: ", ArraySize(g_sw),
           "\nModel: pending orders ", pend, ", open trades ", open,
           "\nModel trades since start: ", g_vTrades, "  wins ", g_vWins, "  ", DoubleToString(g_vR, 2), "R (before costs)");
  }
//+------------------------------------------------------------------+
