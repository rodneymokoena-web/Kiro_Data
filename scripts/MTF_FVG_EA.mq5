//+------------------------------------------------------------------+
//|                                                  MTF_FVG_EA.mq5  |
//|  D/4H/1H POI -> 15m BOS -> 5m zone (stop) + 1m FVG entry         |
//+------------------------------------------------------------------+
#property copyright "MTF-FVG"
#property version   "1.00"
#property description "D/4H/1H bias (swing sweep / inside FVG) -> 15m break of structure ->"
#property description "5m zone (stop) + 1m entry FVG -> limit order at the 1m FVG near edge"
#property description "(placed before price touches it), with an alert when the order is placed."

#include <Trade/Trade.mqh>

//--- enums
enum ENUM_SWEEP_TYPE { SWEEP_WICK = 0, SWEEP_CLOSE = 1, SWEEP_BOTH = 2 };
enum ENUM_BIAS_MODE
  {
   BIAS_D_4H_1H = 0,   // D + 4H + 1H
   BIAS_D_4H    = 1,   // D + 4H
   BIAS_4H_1H   = 2,   // 4H + 1H
   BIAS_D       = 3,   // D only
   BIAS_4H      = 4,   // 4H only
   BIAS_1H      = 5    // 1H only
  };
enum ENUM_TP_MODE    { TP_RR = 0, TP_STRUCTURE = 1 };
enum ENUM_LOT_MODE   { LOT_FIXED = 0, LOT_RISK_PCT = 1 };
enum ENUM_RR_CHOICE  { RR_2R = 0, RR_3R = 1 };
enum ENUM_RISK_CHOICE{ RISK_1_PCT = 0, RISK_HALF_PCT = 1 };
enum ENUM_STOP_MODE  { STOP_1M_SWING = 0, STOP_5M_ZONE = 1 };
enum ENUM_ENTRY_TYPE { ENTRY_LIMIT = 0, ENTRY_MARKET_ON_TOUCH = 1 };

//--- inputs
input group "Timeframes"
input ENUM_TIMEFRAMES InpBiasTFD  = PERIOD_D1;   // Bias timeframe (Daily)
input ENUM_TIMEFRAMES InpBiasTF   = PERIOD_H4;   // Bias timeframe (4H)
input ENUM_TIMEFRAMES InpBiasTF2  = PERIOD_H1;   // Second bias timeframe (1H)
input ENUM_TIMEFRAMES InpStructTF = PERIOD_M15;  // Structure timeframe
input ENUM_TIMEFRAMES InpEntryTF  = PERIOD_M5;   // Bias-check timeframe (Rule 1 bars, 5m)
input ENUM_TIMEFRAMES InpZoneTF   = PERIOD_M5;   // Rule 3 zone timeframe (sets the stop, 5m)
input ENUM_TIMEFRAMES InpEntryFvgTF = PERIOD_M1; // Rule 4 entry FVG timeframe (1m; = zone TF -> enter at zone edge)

input group "Bias (D / 4H / 1H)"
input ENUM_BIAS_MODE InpBiasMode  = BIAS_D_4H_1H; // Rule 1 bias timeframes
input bool            InpUseSweep   = true;       // Bias: swing sweep
input bool            InpUseFvg4    = true;       // Bias: price inside FVG
input int             InpSwLen4     = 5;          // Swing length (D, 4H and 1H)
input ENUM_SWEEP_TYPE InpSweepType  = SWEEP_BOTH; // Sweep type
input int             InpBiasBars   = 500;        // Bias valid for (entry-TF bars)

input group "15m structure"
input int             InpSwLen15    = 3;          // 15m swing length

input group "Entry zone (Rule 3)"
input bool            InpUseIFVG    = true;       // Allow inverse-FVG zones
input int             InpMaxZones   = 30;         // Max stored zones (oldest dropped)

input group "Trade management"
input bool            InpAllowLong  = true;
input bool            InpAllowShort = true;
input ENUM_STOP_MODE  InpStopMode   = STOP_1M_SWING; // Rule 5 stop: previous 1m swing, or 5m zone far edge
input int             InpSwingLen1  = 3;          // 1m swing length (bars each side)
input int             InpSwingLookback = 300;     // 1m bars searched back for the swing
input int             InpStopBufPts = 0;          // Extra points beyond the 1m swing (0 = exactly at it)
input double          InpSlBufPct   = 5.0;        // 5m-zone mode: buffer beyond zone (% of zone height)
input ENUM_TP_MODE    InpTpMode     = TP_RR;      // Take-profit mode
input ENUM_RR_CHOICE  InpRRChoice   = RR_2R;      // RR target: 2R or 3R
input bool            InpOneAtATime = true;       // One open position at a time

input group "Entry order"
input ENUM_ENTRY_TYPE InpEntryType  = ENTRY_LIMIT; // Limit order at entry (before touch), or market on touch
input bool            InpCancelOnRemove = true;  // Delete this EA's pending orders when the EA is removed

input group "Alerts"
input bool            InpAlertPopup = true;       // Popup + sound in MT5 when a limit order is placed
input bool            InpAlertPush  = false;      // Push to MT5 mobile app (needs MetaQuotes ID in Options)
input bool            InpAlertEmail = false;      // Email (needs email set up in Options)

input group "Position sizing"
input ENUM_LOT_MODE   InpLotMode    = LOT_RISK_PCT;
input double          InpFixedLots  = 0.01;       // Fixed lots
input ENUM_RISK_CHOICE InpRiskChoice = RISK_1_PCT; // Risk per trade: 1% or 0.5% of balance

input group "Filters"
input int             InpMaxSpreadPts = 0;        // Max spread in points (0 = off)
input bool            InpUseSession   = false;    // Restrict to trading hours
input int             InpStartHour    = 7;        // Start hour (server time)
input int             InpEndHour      = 20;       // End hour (server time)

input group "General"
input ulong           InpMagic      = 20260511;
input int             InpSlippage   = 20;         // Max deviation (points)
input bool            InpDrawZones  = true;       // Draw zones on chart
input color           InpColSell    = clrTomato;
input color           InpColBuy     = clrMediumSeaGreen;

input group "Chart drawings"
input bool            InpShowBos    = true;       // Show 15m BOS (line + label)
input bool            InpShowLegFvg = true;       // Show last 1m FVG on the BOS leg
input int             InpMaxBos     = 10;         // Keep the last N BOS drawings
input color           InpColBosDn   = clrRed;
input color           InpColBosUp   = clrLime;
input color           InpColLegFvg  = clrOrange;
input int             InpFvgBoxMin  = 60;         // 1m FVG box length (minutes)
input int             InpMaxFvgBoxes = 300;       // 1m FVG boxes kept (oldest removed beyond this)

//--- zone storage
struct Zone
  {
   double top;     // Rule 3 zone (5m): sets the stop
   double bot;
   double etop;    // Rule 4 entry FVG (1m): limit price is its near edge
   double ebot;
   datetime et0;
   double tgt;     // structure target (broken 15m swing)
   double swingSL; // 1m swing used for the stop (0 = 5m-zone mode)
   int    dir;     // -1 sell, +1 buy
   bool   armed;   // true until traded (filled / tapped) or skipped
   ulong  id;
   datetime t0;
   ulong  ticket;  // resting limit order ticket (0 = none)
   datetime lastTry; // last time a limit placement was attempted
  };
Zone   g_zones[];
ulong  g_nextId = 1;

//--- state
CTrade   trade;
datetime g_lastEntryBar  = 0;
datetime g_lastStructBar = 0;
datetime g_lastZoneBar   = 0;
datetime g_lastEntryFvgBar = 0;
long     g_barCount      = 0;

// One slot per selected bias timeframe (Daily / 4H / 1H, chosen by InpBiasMode)
struct BiasTF
  {
   ENUM_TIMEFRAMES tf;
   datetime lastBar;
   double   swHigh, swLow;     // latest swings
   double   fbT, fbB;          // latest bearish FVG
   double   fuT, fuB;          // latest bullish FVG
  };
BiasTF   g_bias[3];
int      g_biasCount = 1;
long     g_shortBiasBar = -1, g_longBiasBar = -1;

double   g_lastPL15 = 0, g_lastPH15 = 0;        // latest 15m swings
datetime g_lastPL15T = 0, g_lastPH15T = 0;      // their candle times (for drawing)
long     g_bosId = 0;
double   g_brokenLow15 = 0, g_brokenHigh15 = 0;
// Setup building, per side: [0] = short, [1] = long.
// After a 15m BOS both searches arm; a setup is complete when both pieces exist.
struct Piece
  {
   bool     has;
   double   top, bot;
   datetime t0;
  };
Piece    g_p5[2], g_p1[2];        // 5m zone piece, 1m entry-FVG piece
bool     g_arm5[2], g_arm1[2];    // searches armed

const string PFX = "MTFFVG_";
string   g_sym = "";             // symbol the state belongs to
string   g_fvgObjs[];             // permanent 1m FVG boxes (entry + BOS leg), oldest first

//+------------------------------------------------------------------+
//| Helpers                                                          |
//+------------------------------------------------------------------+
bool LoadSeries(ENUM_TIMEFRAMES tf, int n, double &hi[], double &lo[])
  {
   ArraySetAsSeries(hi, true);
   ArraySetAsSeries(lo, true);
   if(CopyHigh(_Symbol, tf, 0, n, hi) < n) return false;
   if(CopyLow(_Symbol, tf, 0, n, lo) < n)  return false;
   return true;
  }

// Most recent confirmed pivot high (series arrays, shift 0 = forming bar).
bool FindPivotHigh(const double &h[], int n, int L, double &val)
  {
   for(int s = L + 1; s < n - L; s++)
     {
      bool ok = true;
      for(int k = 1; k <= L && ok; k++)
        {
         if(h[s] < h[s - k])  ok = false;   // right side must not exceed
         if(h[s] <= h[s + k]) ok = false;   // left side must be lower
        }
      if(ok) { val = h[s]; return true; }
     }
   return false;
  }

// Same as FindPivotHigh/Low, also returning the pivot's bar shift.
bool FindPivotHighS(const double &h[], int n, int L, double &val, int &shift)
  {
   for(int s = L + 1; s < n - L; s++)
     {
      bool ok = true;
      for(int k = 1; k <= L && ok; k++)
        { if(h[s] < h[s - k] || h[s] <= h[s + k]) ok = false; }
      if(ok) { val = h[s]; shift = s; return true; }
     }
   return false;
  }

bool FindPivotLowS(const double &l[], int n, int L, double &val, int &shift)
  {
   for(int s = L + 1; s < n - L; s++)
     {
      bool ok = true;
      for(int k = 1; k <= L && ok; k++)
        { if(l[s] > l[s - k] || l[s] >= l[s + k]) ok = false; }
      if(ok) { val = l[s]; shift = s; return true; }
     }
   return false;
  }

bool FindPivotLow(const double &l[], int n, int L, double &val)
  {
   for(int s = L + 1; s < n - L; s++)
     {
      bool ok = true;
      for(int k = 1; k <= L && ok; k++)
        {
         if(l[s] > l[s - k])  ok = false;
         if(l[s] >= l[s + k]) ok = false;
        }
      if(ok) { val = l[s]; return true; }
     }
   return false;
  }

bool Overlap(double aT, double aB, double bT, double bB) { return (aB <= bT && aT >= bB); }

double RRValue()      { return (InpRRChoice == RR_3R) ? 3.0 : 2.0; }
double RiskPercent()  { return (InpRiskChoice == RISK_HALF_PCT) ? 0.5 : 1.0; }

void SendAlert(const string msg)
  {
   if(InpAlertPopup) Alert(msg);
   if(InpAlertPush)  SendNotification(msg);
   if(InpAlertEmail) SendMail("MTF-FVG " + _Symbol, msg);
   Print(msg);
  }

bool OrderIsPending(ulong ticket) { return ticket != 0 && OrderSelect(ticket); }

void CancelOrder(ulong ticket)
  {
   if(OrderIsPending(ticket) && !trade.OrderDelete(ticket))
      PrintFormat("Could not delete order %I64u: retcode=%d (%s)", ticket, trade.ResultRetcode(), trade.ResultRetcodeDescription());
  }

bool HasPosition()
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(PositionGetSymbol(i) == _Symbol && (ulong)PositionGetInteger(POSITION_MAGIC) == InpMagic)
         return true;
     }
   return false;
  }

bool InTradingWindow()
  {
   if(!InpUseSession) return true;
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   if(InpStartHour <= InpEndHour) return (dt.hour >= InpStartHour && dt.hour < InpEndHour);
   return (dt.hour >= InpStartHour || dt.hour < InpEndHour); // overnight window
  }

bool TradeAllowedNow(int dir)
  {
   if(dir < 0 && !InpAllowShort) return false;
   if(dir > 0 && !InpAllowLong)  return false;
   if(!InTradingWindow()) return false;
   if(InpMaxSpreadPts > 0 && SymbolInfoInteger(_Symbol, SYMBOL_SPREAD) > InpMaxSpreadPts) return false;
   return true;
  }

string ZoneName(ulong id) { return PFX + (string)id; }

// 1m FVG boxes: fixed length, visible on M1 / M5 / M15 / H1, kept after the setup ends.
void Make1mFvgBox(const string nm, datetime t0, double top, double bot, color col, int style, int width, const string txt)
  {
   if(ObjectFind(0, nm) >= 0) return;
   datetime t1 = t0 + InpFvgBoxMin * 60;
   if(!ObjectCreate(0, nm, OBJ_RECTANGLE, 0, t0, top, t1, bot)) return;
   ObjectSetInteger(0, nm, OBJPROP_COLOR, col);
   ObjectSetInteger(0, nm, OBJPROP_FILL, false);
   ObjectSetInteger(0, nm, OBJPROP_STYLE, style);
   ObjectSetInteger(0, nm, OBJPROP_WIDTH, width);
   ObjectSetInteger(0, nm, OBJPROP_RAY_RIGHT, false);
   ObjectSetInteger(0, nm, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, nm, OBJPROP_TIMEFRAMES, OBJ_PERIOD_M1 | OBJ_PERIOD_M5 | OBJ_PERIOD_M15 | OBJ_PERIOD_H1);
   ObjectSetString(0, nm, OBJPROP_TEXT, txt);
   int n = ArraySize(g_fvgObjs);
   ArrayResize(g_fvgObjs, n + 1);
   g_fvgObjs[n] = nm;
   while(ArraySize(g_fvgObjs) > InpMaxFvgBoxes)
     {
      ObjectDelete(0, g_fvgObjs[0]);
      ArrayRemove(g_fvgObjs, 0, 1);
     }
  }

void DrawZone(const Zone &z)
  {
   if(!InpDrawZones) return;
   string nm = ZoneName(z.id);
   datetime t2 = TimeCurrent() + PeriodSeconds(InpEntryTF) * 2;
   if(ObjectFind(0, nm) < 0)
      ObjectCreate(0, nm, OBJ_RECTANGLE, 0, z.t0, z.top, t2, z.bot);
   ObjectSetInteger(0, nm, OBJPROP_COLOR, z.dir < 0 ? InpColSell : InpColBuy);
   ObjectSetInteger(0, nm, OBJPROP_FILL, true);
   ObjectSetInteger(0, nm, OBJPROP_BACK, true);
   ObjectSetInteger(0, nm, OBJPROP_RAY_RIGHT, true);
   ObjectSetInteger(0, nm, OBJPROP_SELECTABLE, false);
   string tfn = StringSubstr(EnumToString(InpZoneTF), 7);   // e.g. "M1"
   ObjectSetString(0, nm, OBJPROP_TEXT, tfn + (z.dir < 0 ? " zone (sell)" : " zone (buy)"));
   if(InpEntryFvgTF != InpZoneTF)
      Make1mFvgBox(nm + "e", z.et0, z.etop, z.ebot, clrDodgerBlue, STYLE_SOLID, 2,
                   StringSubstr(EnumToString(InpEntryFvgTF), 7) + " entry FVG");
  }

void FinishZoneDrawing(const Zone &z)
  {
   if(!InpDrawZones) return;
   string nm = ZoneName(z.id);
   if(ObjectFind(0, nm) < 0) return;
   ObjectSetInteger(0, nm, OBJPROP_RAY_RIGHT, false);
   ObjectSetInteger(0, nm, OBJPROP_TIME, 1, TimeCurrent());
  }

void RemoveZone(int idx)
  {
   int n = ArraySize(g_zones);
   if(idx < 0 || idx >= n) return;
   if(InpDrawZones) ObjectDelete(0, ZoneName(g_zones[idx].id));   // the 1m entry FVG box stays
   if(g_zones[idx].ticket != 0)
     {
      CancelOrder(g_zones[idx].ticket);
      PrintFormat("Zone removed: limit order %I64u cancelled", g_zones[idx].ticket);
     }
   for(int i = idx; i < n - 1; i++)
      g_zones[i] = g_zones[i + 1];
   ArrayResize(g_zones, n - 1);
  }

void AddZone(double top, double bot, int dir, datetime t0, double tgt, double etop, double ebot, datetime et0, double swingSL)
  {
   if(ArraySize(g_zones) >= InpMaxZones)
      RemoveZone(0);
   int n = ArraySize(g_zones);
   ArrayResize(g_zones, n + 1);
   g_zones[n].top   = top;
   g_zones[n].bot   = bot;
   g_zones[n].etop  = etop;
   g_zones[n].ebot  = ebot;
   g_zones[n].et0   = et0;
   g_zones[n].swingSL = swingSL;
   g_zones[n].tgt   = tgt;
   g_zones[n].dir   = dir;
   g_zones[n].armed = true;
   g_zones[n].id    = g_nextId++;
   g_zones[n].t0    = t0;
   g_zones[n].ticket  = 0;
   g_zones[n].lastTry = 0;
   DrawZone(g_zones[n]);
   PrintFormat("New %s setup: zone [%s - %s] entry FVG [%s - %s] target %s", dir < 0 ? "SELL" : "BUY",
               DoubleToString(bot, _Digits), DoubleToString(top, _Digits),
               DoubleToString(ebot, _Digits), DoubleToString(etop, _Digits), DoubleToString(tgt, _Digits));
  }

double NormalizeLots(double lots)
  {
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double vmin = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double vmax = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   if(step > 0) lots = MathFloor(lots / step) * step;
   lots = MathMax(vmin, MathMin(vmax, lots));
   return NormalizeDouble(lots, 2);
  }

double CalcLots(double slDistance)
  {
   if(InpLotMode == LOT_FIXED) return NormalizeLots(InpFixedLots);
   double tickVal  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE_LOSS);
   if(tickVal <= 0) tickVal = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tickSize = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tickVal <= 0 || tickSize <= 0 || slDistance <= 0) return NormalizeLots(InpFixedLots);
   double riskMoney  = AccountInfoDouble(ACCOUNT_BALANCE) * RiskPercent() / 100.0;
   double lossPerLot = slDistance / tickSize * tickVal;
   return NormalizeLots(riskMoney / lossPerLot);
  }

//+------------------------------------------------------------------+
//| Bias timeframe update (runs on a new bias-TF bar)                |
//+------------------------------------------------------------------+
void UpdateBiasTF(int b)
  {
   // Use up to 300 bars, or whatever history exists (Daily may have fewer, esp. in the tester)
   int n = MathMin(300, Bars(_Symbol, g_bias[b].tf));
   if(n < 2 * InpSwLen4 + 4) return;
   double hi[], lo[];
   if(!LoadSeries(g_bias[b].tf, n, hi, lo)) return;

   double v;
   if(FindPivotHigh(hi, n, InpSwLen4, v)) g_bias[b].swHigh = v;
   if(FindPivotLow(lo, n, InpSwLen4, v))  g_bias[b].swLow  = v;

   // Most recent bearish FVG: high[s] < low[s+2]; bullish: low[s] > high[s+2]
   bool gotBear = false, gotBull = false;
   for(int s = 1; s < n - 3 && !(gotBear && gotBull); s++)
     {
      if(!gotBear && hi[s] < lo[s + 2]) { g_bias[b].fbT = lo[s + 2]; g_bias[b].fbB = hi[s]; gotBear = true; }
      if(!gotBull && lo[s] > hi[s + 2]) { g_bias[b].fuT = lo[s];     g_bias[b].fuB = hi[s + 2]; gotBull = true; }
     }
  }

//+------------------------------------------------------------------+
//| Bias flags from the last closed entry-TF bar.                    |
//| The same rules run on every selected bias TF (D / 4H / 1H);      |
//| a hit on any of them sets the bias.                              |
//+------------------------------------------------------------------+
void UpdateBias()
  {
   double h1 = iHigh(_Symbol, InpEntryTF, 1);
   double l1 = iLow(_Symbol, InpEntryTF, 1);
   double c1 = iClose(_Symbol, InpEntryTF, 1);
   double h2 = iHigh(_Symbol, InpEntryTF, 2);
   double l2 = iLow(_Symbol, InpEntryTF, 2);

   for(int b = 0; b < g_biasCount; b++)
     {
      double swH = g_bias[b].swHigh, swL = g_bias[b].swLow;

      bool wickHi  = (swH > 0 && h1 > swH && c1 < swH);
      bool closeHi = (swH > 0 && h2 > swH && c1 < swH);
      bool sweepHi = (InpSweepType == SWEEP_WICK) ? wickHi : (InpSweepType == SWEEP_CLOSE) ? closeHi : (wickHi || closeHi);

      bool wickLo  = (swL > 0 && l1 < swL && c1 > swL);
      bool closeLo = (swL > 0 && l2 < swL && c1 > swL);
      bool sweepLo = (InpSweepType == SWEEP_WICK) ? wickLo : (InpSweepType == SWEEP_CLOSE) ? closeLo : (wickLo || closeLo);

      bool inBear = (g_bias[b].fbT > 0 && c1 <= g_bias[b].fbT && c1 >= g_bias[b].fbB);
      bool inBull = (g_bias[b].fuT > 0 && c1 <= g_bias[b].fuT && c1 >= g_bias[b].fuB);

      if((InpUseSweep && sweepHi) || (InpUseFvg4 && inBear)) g_shortBiasBar = g_barCount;
      if((InpUseSweep && sweepLo) || (InpUseFvg4 && inBull)) g_longBiasBar  = g_barCount;
     }
  }

bool ShortBias() { return g_shortBiasBar >= 0 && (g_barCount - g_shortBiasBar) <= InpBiasBars; }
bool LongBias()  { return g_longBiasBar  >= 0 && (g_barCount - g_longBiasBar)  <= InpBiasBars; }

//+------------------------------------------------------------------+
//| Chart drawings: 15m BOS + last 1m FVG on the leg of the break     |
//|  Leg (bearish): from the highest high since the broken swing low  |
//|  formed, down to the break. Mirror for bullish.                   |
//+------------------------------------------------------------------+
bool LegFvg(int dir, datetime fromT, double &top, double &bot, datetime &t0)
  {
   ENUM_TIMEFRAMES tf = InpEntryFvgTF;
   int sp = iBarShift(_Symbol, tf, fromT, false);
   if(sp < 3) return false;
   int n = MathMin(sp, 1000) + 1;
   double hi[], lo[]; datetime tm[];
   ArraySetAsSeries(hi, true); ArraySetAsSeries(lo, true); ArraySetAsSeries(tm, true);
   if(CopyHigh(_Symbol, tf, 0, n, hi) < n || CopyLow(_Symbol, tf, 0, n, lo) < n || CopyTime(_Symbol, tf, 0, n, tm) < n)
      return false;
   // leg start = extreme between the swing and the last closed bar (shift 1)
   int ext = -1;
   for(int s = 1; s < n; s++)
      if(ext < 0 || (dir < 0 ? hi[s] > hi[ext] : lo[s] < lo[ext])) ext = s;
   // most recent FVG inside the leg (shifts 1 .. ext)
   for(int s = 1; s + 2 <= ext; s++)
     {
      if(dir < 0 && hi[s] < lo[s + 2]) { top = lo[s + 2]; bot = hi[s]; t0 = tm[s + 2]; return true; }
      if(dir > 0 && lo[s] > hi[s + 2]) { top = lo[s];     bot = hi[s + 2]; t0 = tm[s + 2]; return true; }
     }
   return false;
  }

void DrawBos(int dir, double lvl, datetime fromT)
  {
   g_bosId++;
   string id = (string)g_bosId;
   datetime now = TimeCurrent();
   color col = dir < 0 ? InpColBosDn : InpColBosUp;
   if(InpShowBos && fromT > 0)
     {
      string ln = PFX + "BOS_" + id, lb = PFX + "BOSL_" + id;
      ObjectCreate(0, ln, OBJ_TREND, 0, fromT, lvl, now, lvl);
      ObjectSetInteger(0, ln, OBJPROP_COLOR, col);
      ObjectSetInteger(0, ln, OBJPROP_WIDTH, 2);
      ObjectSetInteger(0, ln, OBJPROP_RAY_RIGHT, false);
      ObjectSetInteger(0, ln, OBJPROP_SELECTABLE, false);
      ObjectCreate(0, lb, OBJ_TEXT, 0, now, lvl);
      ObjectSetString(0, lb, OBJPROP_TEXT, "BOS");
      ObjectSetInteger(0, lb, OBJPROP_COLOR, col);
      ObjectSetInteger(0, lb, OBJPROP_ANCHOR, dir < 0 ? ANCHOR_LEFT_UPPER : ANCHOR_LEFT_LOWER);
      ObjectSetInteger(0, lb, OBJPROP_SELECTABLE, false);
     }
   double t, b; datetime t0;
   if(InpShowLegFvg && fromT > 0 && LegFvg(dir, fromT, t, b, t0))
     {
      Make1mFvgBox(PFX + "LEG_" + id, t0, t, b, InpColLegFvg, STYLE_DOT, 1,
                   StringSubstr(EnumToString(InpEntryFvgTF), 7) + " FVG (BOS leg)");
     }
   // keep only the last N
   string old = (string)(g_bosId - InpMaxBos);
   ObjectDelete(0, PFX + "BOS_" + old);
   ObjectDelete(0, PFX + "BOSL_" + old);      // 1m FVG boxes are kept (see InpMaxFvgBoxes)
   ChartRedraw();
  }

//+------------------------------------------------------------------+
//| Structure TF update + BOS detection (runs on a new 15m bar)      |
//+------------------------------------------------------------------+
void UpdateStructure()
  {
   const int n = 200;
   double hi[], lo[];
   if(!LoadSeries(InpStructTF, n, hi, lo)) return;

   double v;
   int sh;
   if(FindPivotLowS(lo, n, InpSwLen15, v, sh))  { g_lastPL15 = v; g_lastPL15T = iTime(_Symbol, InpStructTF, sh); }
   if(FindPivotHighS(hi, n, InpSwLen15, v, sh)) { g_lastPH15 = v; g_lastPH15T = iTime(_Symbol, InpStructTF, sh); }

   double c1 = iClose(_Symbol, InpStructTF, 1);
   double c2 = iClose(_Symbol, InpStructTF, 2);

   bool bosDown = ShortBias() && g_lastPL15 > 0 && c1 < g_lastPL15 && c2 >= g_lastPL15;
   bool bosUp   = LongBias()  && g_lastPH15 > 0 && c1 > g_lastPH15 && c2 <= g_lastPH15;

   if(bosDown)
     {
      g_brokenLow15 = g_lastPL15;
      StartSetup(0);
      PrintFormat("15m BOS DOWN through %s", DoubleToString(g_brokenLow15, _Digits));
      DrawBos(-1, g_brokenLow15, g_lastPL15T);
     }
   if(bosUp)
     {
      g_brokenHigh15 = g_lastPH15;
      StartSetup(1);
      PrintFormat("15m BOS UP through %s", DoubleToString(g_brokenHigh15, _Digits));
      DrawBos(1, g_brokenHigh15, g_lastPH15T);
     }
  }

//+------------------------------------------------------------------+
//| Remove zones price has closed through                            |
//+------------------------------------------------------------------+
void MitigateZones()
  {
   double c1 = iClose(_Symbol, InpZoneTF, 1);
   for(int i = ArraySize(g_zones) - 1; i >= 0; i--)
     {
      if(g_zones[i].dir < 0 && c1 > g_zones[i].top) RemoveZone(i);
      else if(g_zones[i].dir > 0 && c1 < g_zones[i].bot) RemoveZone(i);
     }
  }

//+------------------------------------------------------------------+
//| Setup building (Rule 3 zone on 5m + Rule 4 entry FVG on 1m)      |
//+------------------------------------------------------------------+
double SideLevel(int sd) { return sd == 0 ? g_brokenLow15 : g_brokenHigh15; }
bool   SideAllowed(int sd) { return sd == 0 ? InpAllowShort : InpAllowLong; }

void StartSetup(int sd)
  {
   g_arm5[sd] = true;
   g_arm1[sd] = true;
   g_p5[sd].has = false;
   g_p1[sd].has = false;
  }

// First FVG / inverse FVG on tf (closed bars 1..3) that contains the level.
// sd 0 = bearish (short), 1 = bullish (long).
bool FindFvg(ENUM_TIMEFRAMES tf, int sd, double level, double &top, double &bot, datetime &t0)
  {
   double h1 = iHigh(_Symbol, tf, 1), l1 = iLow(_Symbol, tf, 1);
   double h2 = iHigh(_Symbol, tf, 2), l2 = iLow(_Symbol, tf, 2);
   double h3 = iHigh(_Symbol, tf, 3), l3 = iLow(_Symbol, tf, 3);
   double c1 = iClose(_Symbol, tf, 1);
   t0 = iTime(_Symbol, tf, 3);
   if(sd == 0)
     {
      if(h1 < l3 && Overlap(l3, h1, level, level))                                { top = l3; bot = h1; return true; }
      if(InpUseIFVG && l2 > h3 && c1 < h3 && Overlap(l2, h3, level, level))        { top = l2; bot = h3; return true; }
     }
   else
     {
      if(l1 > h3 && Overlap(l1, h3, level, level))                                { top = l1; bot = h3; return true; }
      if(InpUseIFVG && h2 < l3 && c1 > l3 && Overlap(l3, h2, level, level))        { top = l3; bot = h2; return true; }
     }
   return false;
  }

// New zone-TF (5m) bar: drop a pending 5m piece that price closed through, then search.
void CaptureZonePieces()
  {
   double c1 = iClose(_Symbol, InpZoneTF, 1);
   for(int sd = 0; sd < 2; sd++)
     {
      if(g_p5[sd].has && ((sd == 0 && c1 > g_p5[sd].top) || (sd == 1 && c1 < g_p5[sd].bot)))
        {
         g_p5[sd].has = false;               // zone failed before an entry FVG paired with it
         g_arm1[sd] = false;
         g_p1[sd].has = false;
         Print(sd == 0 ? "Pending SELL zone closed through: setup cancelled" : "Pending BUY zone closed through: setup cancelled");
        }
      double level = SideLevel(sd);
      if(!SideAllowed(sd) || !g_arm5[sd] || level <= 0) continue;
      double t, b; datetime t0;
      if(FindFvg(InpZoneTF, sd, level, t, b, t0))
        {
         g_p5[sd].has = true; g_p5[sd].top = t; g_p5[sd].bot = b; g_p5[sd].t0 = t0;
         g_arm5[sd] = false;
        }
     }
  }

// New entry-FVG-TF (1m) bar: drop a pending 1m piece price closed through (and re-arm), then search.
void CaptureEntryPieces()
  {
   double c1 = iClose(_Symbol, InpEntryFvgTF, 1);
   for(int sd = 0; sd < 2; sd++)
     {
      if(g_p1[sd].has && ((sd == 0 && c1 > g_p1[sd].top) || (sd == 1 && c1 < g_p1[sd].bot)))
        {
         g_p1[sd].has = false;
         g_arm1[sd] = (g_arm5[sd] || g_p5[sd].has);   // look for a new entry FVG while the setup lives
        }
      double level = SideLevel(sd);
      if(!SideAllowed(sd) || !g_arm1[sd] || level <= 0) continue;
      double t, b; datetime t0;
      if(FindFvg(InpEntryFvgTF, sd, level, t, b, t0))
        {
         g_p1[sd].has = true; g_p1[sd].top = t; g_p1[sd].bot = b; g_p1[sd].t0 = t0;
         g_arm1[sd] = false;
        }
     }
  }

// Most recent confirmed 1m swing high above price (sd 0, sell) or swing low below price (sd 1, buy).
bool FindStopSwing(int sd, double price, double &val)
  {
   int L = InpSwingLen1;
   int n = MathMin(InpSwingLookback + L + 1, Bars(_Symbol, InpEntryFvgTF));
   if(n < 2 * L + 3) return false;
   double hi[], lo[];
   if(!LoadSeries(InpEntryFvgTF, n, hi, lo)) return false;
   for(int s = L + 1; s < n - L; s++)              // shift 0 = forming bar; L+1 = newest confirmed
     {
      bool ok = true;
      for(int k = 1; k <= L && ok; k++)
        {
         if(sd == 0) { if(hi[s] < hi[s - k] || hi[s] <= hi[s + k]) ok = false; }
         else        { if(lo[s] > lo[s - k] || lo[s] >= lo[s + k]) ok = false; }
        }
      if(!ok) continue;
      if(sd == 0 && hi[s] > price) { val = hi[s]; return true; }
      if(sd == 1 && lo[s] < price) { val = lo[s]; return true; }
     }
   return false;
  }

// Both pieces present -> one tradable setup.
void PairPieces()
  {
   for(int sd = 0; sd < 2; sd++)
     {
      if(!g_p5[sd].has || !g_p1[sd].has) continue;
      double swingSL = 0;
      if(InpStopMode == STOP_1M_SWING)
        {
         double entry = (sd == 0) ? g_p1[sd].bot : g_p1[sd].top;
         if(!FindStopSwing(sd, entry, swingSL))
           {
            PrintFormat("%s setup skipped: no 1m swing %s the entry within %d bars", sd == 0 ? "SELL" : "BUY",
                        sd == 0 ? "above" : "below", InpSwingLookback);
            g_p5[sd].has = false; g_p1[sd].has = false;
            continue;
           }
        }
      AddZone(g_p5[sd].top, g_p5[sd].bot, sd == 0 ? -1 : 1, g_p5[sd].t0, SideLevel(sd),
              g_p1[sd].top, g_p1[sd].bot, g_p1[sd].t0, swingSL);
      g_p5[sd].has = false;
      g_p1[sd].has = false;
     }
  }

//+------------------------------------------------------------------+
//| SL / TP for a zone given an entry price                          |
//+------------------------------------------------------------------+
bool CalcLevels(int idx, double entry, double &sl, double &tp, double &risk)
  {
   int    dir = g_zones[idx].dir;
   double top = g_zones[idx].top, bot = g_zones[idx].bot, tgt = g_zones[idx].tgt;
   double buf = (top - bot) * InpSlBufPct / 100.0;
   double minDist = (double)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * _Point;
   bool   useSwing = (InpStopMode == STOP_1M_SWING && g_zones[idx].swingSL > 0);
   double swBuf = InpStopBufPts * _Point;
   if(dir < 0)
     {
      sl   = useSwing ? g_zones[idx].swingSL + swBuf : top + buf;
      risk = sl - entry;
      if(risk <= 0) return false;              // price already beyond the stop
      if(risk < minDist) { sl = entry + minDist; risk = minDist; }
      tp = (InpTpMode == TP_STRUCTURE && tgt > 0 && tgt < entry) ? tgt : entry - risk * RRValue();
      if(entry - tp < minDist) tp = entry - minDist;
     }
   else
     {
      sl   = useSwing ? g_zones[idx].swingSL - swBuf : bot - buf;
      risk = entry - sl;
      if(risk <= 0) return false;
      if(risk < minDist) { sl = entry - minDist; risk = minDist; }
      tp = (InpTpMode == TP_STRUCTURE && tgt > 0 && tgt > entry) ? tgt : entry + risk * RRValue();
      if(tp - entry < minDist) tp = entry + minDist;
     }
   sl = NormalizeDouble(sl, _Digits);
   tp = NormalizeDouble(tp, _Digits);
   return true;
  }

double RoundToTick(double price)
  {
   double ts = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(ts > 0) price = MathRound(price / ts) * ts;
   return NormalizeDouble(price, _Digits);
  }

//+------------------------------------------------------------------+
//| Place a resting limit order at the zone's near edge              |
//|  Sell limit at the zone bottom, buy limit at the zone top.       |
//+------------------------------------------------------------------+
void PlaceLimit(int idx)
  {
   g_zones[idx].lastTry = TimeCurrent();
   int    dir   = g_zones[idx].dir;
   double entry = RoundToTick(dir < 0 ? g_zones[idx].ebot : g_zones[idx].etop);   // 1m entry FVG near edge
   double bid   = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask   = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double minDist = (double)MathMax(SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL),
                                    SymbolInfoInteger(_Symbol, SYMBOL_TRADE_FREEZE_LEVEL)) * _Point;

   // A limit must sit on the far side of the current price; if price is too close, wait.
   if(dir < 0 && entry - bid < minDist + _Point) return;
   if(dir > 0 && ask - entry < minDist + _Point) return;

   double sl, tp, risk;
   if(!CalcLevels(idx, entry, sl, tp, risk)) return;
   double lots = CalcLots(risk);

   ENUM_ORDER_TYPE_TIME tt = ORDER_TIME_GTC;
   if((SymbolInfoInteger(_Symbol, SYMBOL_EXPIRATION_MODE) & SYMBOL_EXPIRATION_GTC) == 0) tt = ORDER_TIME_DAY;

   trade.SetTypeFilling(ORDER_FILLING_RETURN);          // pending orders
   bool ok = (dir < 0) ? trade.SellLimit(lots, entry, _Symbol, sl, tp, tt, 0, "MTF-FVG sell limit")
                       : trade.BuyLimit(lots, entry, _Symbol, sl, tp, tt, 0, "MTF-FVG buy limit");
   trade.SetTypeFillingBySymbol(_Symbol);               // back to market-order filling

   if(ok && trade.ResultOrder() > 0)
     {
      g_zones[idx].ticket = trade.ResultOrder();
      SendAlert(StringFormat("MTF-FVG %s: %s LIMIT placed @ %s | SL %s | TP %s | %.2f lots | %s target",
                _Symbol, dir < 0 ? "SELL" : "BUY",
                DoubleToString(entry, _Digits), DoubleToString(sl, _Digits), DoubleToString(tp, _Digits),
                lots, InpTpMode == TP_STRUCTURE ? "structure" : (InpRRChoice == RR_3R ? "3R" : "2R")));
     }
   else
      PrintFormat("Limit order failed: retcode=%d (%s)", trade.ResultRetcode(), trade.ResultRetcodeDescription());
  }

//+------------------------------------------------------------------+
//| Market entry on touch (used in market mode, or as a fallback     |
//| when a limit could not rest before price reached the zone)       |
//+------------------------------------------------------------------+
void MarketEntry(int idx)
  {
   g_zones[idx].armed = false;                 // a zone is only ever traded once
   FinishZoneDrawing(g_zones[idx]);

   int dir = g_zones[idx].dir;
   if(!TradeAllowedNow(dir)) return;
   if(InpOneAtATime && HasPosition()) return;

   double entry = (dir < 0) ? SymbolInfoDouble(_Symbol, SYMBOL_BID) : SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double sl, tp, risk;
   if(!CalcLevels(idx, entry, sl, tp, risk)) return;
   double lots = CalcLots(risk);

   bool ok = (dir < 0) ? trade.Sell(lots, _Symbol, 0.0, sl, tp, "MTF-FVG sell")
                       : trade.Buy(lots, _Symbol, 0.0, sl, tp, "MTF-FVG buy");
   if(ok)
      PrintFormat("%s %.2f lots @ market %s SL %s TP %s", dir < 0 ? "SELL" : "BUY", lots,
                  DoubleToString(entry, _Digits), DoubleToString(sl, _Digits), DoubleToString(tp, _Digits));
   else
      PrintFormat("Order failed: retcode=%d (%s)", trade.ResultRetcode(), trade.ResultRetcodeDescription());
  }

//+------------------------------------------------------------------+
//| Per-tick management of zones and their orders                    |
//+------------------------------------------------------------------+
void ManageZones()
  {
   int n = ArraySize(g_zones);
   if(n == 0) return;
   double bid  = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask  = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   bool   busy = InpOneAtATime && HasPosition();

   for(int i = n - 1; i >= 0; i--)
     {
      if(!g_zones[i].armed) continue;
      int  dir     = g_zones[i].dir;
      bool touched = (dir < 0) ? (bid >= g_zones[i].ebot) : (ask <= g_zones[i].etop);

      // 1) A limit order is (or was) resting for this zone
      if(g_zones[i].ticket != 0)
        {
         ulong tk = g_zones[i].ticket;
         if(OrderIsPending(tk))
           {
            // Pull the order while another trade is open or trading is not allowed right now.
            if(busy || !TradeAllowedNow(dir))
              {
               CancelOrder(tk);
               g_zones[i].ticket = 0;
              }
            continue;
           }
         if(!HistoryOrderSelect(tk)) continue;  // history not updated yet; check next tick
         ENUM_ORDER_STATE st = (ENUM_ORDER_STATE)HistoryOrderGetInteger(tk, ORDER_STATE);
         g_zones[i].ticket = 0;
         if(st == ORDER_STATE_EXPIRED) continue;   // re-place later
         g_zones[i].armed = false;                 // filled, or cancelled by you
         FinishZoneDrawing(g_zones[i]);
         PrintFormat("Limit order %I64u %s", tk, st == ORDER_STATE_FILLED || st == ORDER_STATE_PARTIAL ? "filled" : "closed (not re-placed)");
         continue;
        }

      // 2) No order resting
      if(touched)
        {
         // Market mode, or the limit could not be placed in time -> enter at market (or skip if blocked)
         MarketEntry(i);
         continue;
        }
      if(InpEntryType == ENTRY_LIMIT && !busy && TradeAllowedNow(dir) && TimeCurrent() - g_zones[i].lastTry >= 30)
         PlaceLimit(i);
     }
  }

//+------------------------------------------------------------------+
//| New entry-TF bar processing                                      |
//+------------------------------------------------------------------+
void OnNewBar()
  {
   g_barCount++;

   for(int b = 0; b < g_biasCount; b++)
     {
      datetime bb = iTime(_Symbol, g_bias[b].tf, 0);
      if(bb != g_bias[b].lastBar) { g_bias[b].lastBar = bb; UpdateBiasTF(b); }
     }

   UpdateBias();

   datetime sb = iTime(_Symbol, InpStructTF, 0);
   if(sb != g_lastStructBar) { g_lastStructBar = sb; UpdateStructure(); }

  }

//+------------------------------------------------------------------+
//| New zone-TF bar (1m by default): Rule 3 zone deletion + capture  |
//+------------------------------------------------------------------+
void OnNewZoneBar()
  {
   MitigateZones();          // setups whose 5m zone was closed through
   CaptureZonePieces();      // Rule 3: 5m zone
   PairPieces();
  }

//+------------------------------------------------------------------+
//| New entry-FVG-TF bar (1m): Rule 4 entry FVG                      |
//+------------------------------------------------------------------+
void OnNewEntryFvgBar()
  {
   CaptureEntryPieces();
   PairPieces();
  }

//+------------------------------------------------------------------+
int OnInit()
  {
   if(InpSwLen4 < 1 || InpSwLen15 < 1 || InpMaxZones < 1 || InpSwingLen1 < 1 || InpSwingLookback < 10 || InpMaxBos < 1
      || InpFvgBoxMin < 1 || InpMaxFvgBoxes < 1)
     {
      Print("Invalid inputs");
      return INIT_PARAMETERS_INCORRECT;
     }
   if(PeriodSeconds(InpStructTF) <= PeriodSeconds(InpEntryTF) || PeriodSeconds(InpZoneTF) > PeriodSeconds(InpEntryTF)
      || PeriodSeconds(InpEntryFvgTF) > PeriodSeconds(InpZoneTF))
     {
      Print("Timeframes must satisfy: Structure > Bias-check TF >= Zone TF >= Entry FVG TF");
      return INIT_PARAMETERS_INCORRECT;
     }
   bool useD  = (InpBiasMode == BIAS_D_4H_1H || InpBiasMode == BIAS_D_4H || InpBiasMode == BIAS_D);
   bool use4H = (InpBiasMode == BIAS_D_4H_1H || InpBiasMode == BIAS_D_4H || InpBiasMode == BIAS_4H_1H || InpBiasMode == BIAS_4H);
   bool use1H = (InpBiasMode == BIAS_D_4H_1H || InpBiasMode == BIAS_4H_1H || InpBiasMode == BIAS_1H);
   ZeroMemory(g_bias);
   g_biasCount = 0;
   if(useD)  g_bias[g_biasCount++].tf = InpBiasTFD;
   if(use4H) g_bias[g_biasCount++].tf = InpBiasTF;
   if(use1H) g_bias[g_biasCount++].tf = InpBiasTF2;
   for(int b = 0; b < g_biasCount; b++)
      if(PeriodSeconds(g_bias[b].tf) <= PeriodSeconds(InpStructTF))
        {
         Print("Every selected bias timeframe must be above the Structure timeframe");
         return INIT_PARAMETERS_INCORRECT;
        }
   string sel = (useD ? "D " : "") + (use4H ? "4H " : "") + (use1H ? "1H" : "");
   PrintFormat("Rule 1 bias timeframes: %s", sel);
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(InpSlippage);
   trade.SetTypeFillingBySymbol(_Symbol);
   // A timeframe switch keeps setups and drawings; a symbol switch (or fresh start) resets them.
   bool keep = (UninitializeReason() == REASON_CHARTCHANGE && g_sym == _Symbol);
   if(!keep)
     {
      if(g_sym != "" && g_sym != _Symbol && InpCancelOnRemove)   // symbol switched: cancel the old symbol's orders
         for(int i = OrdersTotal() - 1; i >= 0; i--)
           {
            ulong tk = OrderGetTicket(i);
            if(tk != 0 && OrderGetString(ORDER_SYMBOL) == g_sym && (ulong)OrderGetInteger(ORDER_MAGIC) == InpMagic)
               trade.OrderDelete(tk);
           }
      ObjectsDeleteAll(0, PFX);
      ArrayResize(g_fvgObjs, 0);
      ArrayResize(g_zones, 0);
      ZeroMemory(g_p5); ZeroMemory(g_p1);
      ArrayInitialize(g_arm5, false); ArrayInitialize(g_arm1, false);
     }
   g_sym = _Symbol;
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason)
  {
   // Switching the chart timeframe keeps the EA loaded: keep drawings, orders and state.
   if(reason == REASON_CHARTCHANGE) return;
   ObjectsDeleteAll(0, PFX);
   ArrayResize(g_fvgObjs, 0);
   if(InpCancelOnRemove)
     {
      for(int i = OrdersTotal() - 1; i >= 0; i--)
        {
         ulong tk = OrderGetTicket(i);
         if(tk == 0) continue;
         if(OrderGetString(ORDER_SYMBOL) == _Symbol && (ulong)OrderGetInteger(ORDER_MAGIC) == InpMagic)
            trade.OrderDelete(tk);
        }
     }
  }

void OnTick()
  {
   datetime bt = iTime(_Symbol, InpEntryTF, 0);
   if(bt == 0) return;
   if(bt != g_lastEntryBar)
     {
      g_lastEntryBar = bt;
      OnNewBar();                 // Rule 1 bias + Rule 2 structure
     }
   datetime zt = iTime(_Symbol, InpZoneTF, 0);
   if(zt != 0 && zt != g_lastZoneBar)
     {
      g_lastZoneBar = zt;
      OnNewZoneBar();             // Rule 3 zones (5m)
     }
   datetime et = iTime(_Symbol, InpEntryFvgTF, 0);
   if(et != 0 && et != g_lastEntryFvgBar)
     {
      g_lastEntryFvgBar = et;
      OnNewEntryFvgBar();         // Rule 4 entry FVG (1m)
     }
   ManageZones();
  }
//+------------------------------------------------------------------+
