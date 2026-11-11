//+------------------------------------------------------------------+
//|                                                  MTF_FVG_EA.mq5  |
//|  4H POI -> 15m BOS -> 5m FVG/iFVG entry (port of the Pine model) |
//+------------------------------------------------------------------+
#property copyright "MTF-FVG"
#property version   "1.00"
#property description "4H bias (swing sweep / inside 4H FVG) -> 15m break of structure ->"
#property description "first overlapping 5m FVG / inverse FVG -> limit order resting at the zone edge"
#property description "(placed before price touches it), with an alert when the order is placed."

#include <Trade/Trade.mqh>

//--- enums
enum ENUM_SWEEP_TYPE { SWEEP_WICK = 0, SWEEP_CLOSE = 1, SWEEP_BOTH = 2 };
enum ENUM_BIAS_MODE  { BIAS_4H_ONLY = 0, BIAS_4H_PLUS_1H = 1 };
enum ENUM_TP_MODE    { TP_RR = 0, TP_STRUCTURE = 1 };
enum ENUM_LOT_MODE   { LOT_FIXED = 0, LOT_RISK_PCT = 1 };
enum ENUM_RR_CHOICE  { RR_2R = 0, RR_3R = 1 };
enum ENUM_RISK_CHOICE{ RISK_1_PCT = 0, RISK_HALF_PCT = 1 };
enum ENUM_ENTRY_TYPE { ENTRY_LIMIT = 0, ENTRY_MARKET_ON_TOUCH = 1 };

//--- inputs
input group "Timeframes"
input ENUM_TIMEFRAMES InpBiasTF   = PERIOD_H4;   // Bias timeframe (4H)
input ENUM_TIMEFRAMES InpBiasTF2  = PERIOD_H1;   // Second bias timeframe (1H)
input ENUM_TIMEFRAMES InpStructTF = PERIOD_M15;  // Structure timeframe
input ENUM_TIMEFRAMES InpEntryTF  = PERIOD_M5;   // Entry timeframe

input group "Bias (4H / 1H)"
input ENUM_BIAS_MODE InpBiasMode  = BIAS_4H_PLUS_1H; // Rule 1 bias: 4H only, or 4H + 1H
input bool            InpUseSweep   = true;       // Bias: swing sweep
input bool            InpUseFvg4    = true;       // Bias: price inside FVG
input int             InpSwLen4     = 5;          // Swing length (4H and 1H)
input ENUM_SWEEP_TYPE InpSweepType  = SWEEP_BOTH; // Sweep type
input int             InpBiasBars   = 500;        // Bias valid for (entry-TF bars)

input group "15m structure"
input int             InpSwLen15    = 3;          // 15m swing length

input group "5m entry zone"
input bool            InpUseIFVG    = true;       // Allow inverse-FVG zones
input int             InpMaxZones   = 30;         // Max stored zones (oldest dropped)

input group "Trade management"
input bool            InpAllowLong  = true;
input bool            InpAllowShort = true;
input double          InpSlBufPct   = 5.0;        // SL buffer beyond zone (% of zone height)
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

//--- zone storage
struct Zone
  {
   double top;
   double bot;
   double tgt;     // structure target (broken 15m swing)
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
long     g_barCount      = 0;

// One slot per bias timeframe: [0] = 4H, [1] = 1H (only used when InpBiasMode = BIAS_4H_PLUS_1H)
struct BiasTF
  {
   ENUM_TIMEFRAMES tf;
   datetime lastBar;
   double   swHigh, swLow;     // latest swings
   double   fbT, fbB;          // latest bearish FVG
   double   fuT, fuB;          // latest bullish FVG
  };
BiasTF   g_bias[2];
int      g_biasCount = 1;
long     g_shortBiasBar = -1, g_longBiasBar = -1;

double   g_lastPL15 = 0, g_lastPH15 = 0;        // latest 15m swings
double   g_brokenLow15 = 0, g_brokenHigh15 = 0;
bool     g_armShort = false, g_armLong = false;

const string PFX = "MTFFVG_";

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
   ObjectSetString(0, nm, OBJPROP_TEXT, z.dir < 0 ? "5m FVG (sell)" : "5m FVG (buy)");
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
   if(InpDrawZones) ObjectDelete(0, ZoneName(g_zones[idx].id));
   if(g_zones[idx].ticket != 0)
     {
      CancelOrder(g_zones[idx].ticket);
      PrintFormat("Zone removed: limit order %I64u cancelled", g_zones[idx].ticket);
     }
   for(int i = idx; i < n - 1; i++)
      g_zones[i] = g_zones[i + 1];
   ArrayResize(g_zones, n - 1);
  }

void AddZone(double top, double bot, int dir, datetime t0, double tgt)
  {
   if(ArraySize(g_zones) >= InpMaxZones)
      RemoveZone(0);
   int n = ArraySize(g_zones);
   ArrayResize(g_zones, n + 1);
   g_zones[n].top   = top;
   g_zones[n].bot   = bot;
   g_zones[n].tgt   = tgt;
   g_zones[n].dir   = dir;
   g_zones[n].armed = true;
   g_zones[n].id    = g_nextId++;
   g_zones[n].t0    = t0;
   g_zones[n].ticket  = 0;
   g_zones[n].lastTry = 0;
   DrawZone(g_zones[n]);
   PrintFormat("New %s zone [%s - %s] target %s", dir < 0 ? "SELL" : "BUY",
               DoubleToString(bot, _Digits), DoubleToString(top, _Digits), DoubleToString(tgt, _Digits));
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
   const int n = 300;
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
//| The same rules run on every bias TF (4H, and 1H if enabled);     |
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
//| Structure TF update + BOS detection (runs on a new 15m bar)      |
//+------------------------------------------------------------------+
void UpdateStructure()
  {
   const int n = 200;
   double hi[], lo[];
   if(!LoadSeries(InpStructTF, n, hi, lo)) return;

   double v;
   if(FindPivotLow(lo, n, InpSwLen15, v))  g_lastPL15 = v;
   if(FindPivotHigh(hi, n, InpSwLen15, v)) g_lastPH15 = v;

   double c1 = iClose(_Symbol, InpStructTF, 1);
   double c2 = iClose(_Symbol, InpStructTF, 2);

   bool bosDown = ShortBias() && g_lastPL15 > 0 && c1 < g_lastPL15 && c2 >= g_lastPL15;
   bool bosUp   = LongBias()  && g_lastPH15 > 0 && c1 > g_lastPH15 && c2 <= g_lastPH15;

   if(bosDown)
     {
      g_brokenLow15 = g_lastPL15;
      g_armShort = true;
      PrintFormat("15m BOS DOWN through %s", DoubleToString(g_brokenLow15, _Digits));
     }
   if(bosUp)
     {
      g_brokenHigh15 = g_lastPH15;
      g_armLong = true;
      PrintFormat("15m BOS UP through %s", DoubleToString(g_brokenHigh15, _Digits));
     }
  }

//+------------------------------------------------------------------+
//| Remove zones price has closed through                            |
//+------------------------------------------------------------------+
void MitigateZones()
  {
   double c1 = iClose(_Symbol, InpEntryTF, 1);
   for(int i = ArraySize(g_zones) - 1; i >= 0; i--)
     {
      if(g_zones[i].dir < 0 && c1 > g_zones[i].top) RemoveZone(i);
      else if(g_zones[i].dir > 0 && c1 < g_zones[i].bot) RemoveZone(i);
     }
  }

//+------------------------------------------------------------------+
//| Capture first overlapping FVG / iFVG after a BOS                 |
//|  Pine [0],[1],[2] -> MQL closed shifts 1,2,3                     |
//+------------------------------------------------------------------+
void CaptureZones()
  {
   double h1 = iHigh(_Symbol, InpEntryTF, 1), l1 = iLow(_Symbol, InpEntryTF, 1);
   double h2 = iHigh(_Symbol, InpEntryTF, 2), l2 = iLow(_Symbol, InpEntryTF, 2);
   double h3 = iHigh(_Symbol, InpEntryTF, 3), l3 = iLow(_Symbol, InpEntryTF, 3);
   double c1 = iClose(_Symbol, InpEntryTF, 1);
   datetime t3 = iTime(_Symbol, InpEntryTF, 3);

   if(InpAllowShort && g_armShort && g_brokenLow15 > 0)
     {
      bool bearFvg  = (h1 < l3);                             // gap: top=l3, bottom=h1
      bool ifvgBear = InpUseIFVG && (l2 > h3) && (c1 < h3);  // prior bull gap violated: top=l2, bottom=h3
      if(bearFvg && Overlap(l3, h1, g_brokenLow15, g_brokenLow15))
        { AddZone(l3, h1, -1, t3, g_brokenLow15); g_armShort = false; }
      else if(ifvgBear && Overlap(l2, h3, g_brokenLow15, g_brokenLow15))
        { AddZone(l2, h3, -1, t3, g_brokenLow15); g_armShort = false; }
     }

   if(InpAllowLong && g_armLong && g_brokenHigh15 > 0)
     {
      bool bullFvg  = (l1 > h3);                             // gap: top=l1, bottom=h3
      bool ifvgBull = InpUseIFVG && (h2 < l3) && (c1 > l3);  // prior bear gap violated: top=l3, bottom=h2
      if(bullFvg && Overlap(l1, h3, g_brokenHigh15, g_brokenHigh15))
        { AddZone(l1, h3, 1, t3, g_brokenHigh15); g_armLong = false; }
      else if(ifvgBull && Overlap(l3, h2, g_brokenHigh15, g_brokenHigh15))
        { AddZone(l3, h2, 1, t3, g_brokenHigh15); g_armLong = false; }
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
   if(dir < 0)
     {
      sl   = top + buf;
      risk = sl - entry;
      if(risk <= 0) return false;              // price already beyond the stop
      if(risk < minDist) { sl = entry + minDist; risk = minDist; }
      tp = (InpTpMode == TP_STRUCTURE && tgt > 0 && tgt < entry) ? tgt : entry - risk * RRValue();
      if(entry - tp < minDist) tp = entry - minDist;
     }
   else
     {
      sl   = bot - buf;
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
   double entry = RoundToTick(dir < 0 ? g_zones[idx].bot : g_zones[idx].top);
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
      bool touched = (dir < 0) ? (bid >= g_zones[i].bot) : (ask <= g_zones[i].top);

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

   MitigateZones();
   CaptureZones();
  }

//+------------------------------------------------------------------+
int OnInit()
  {
   if(InpSwLen4 < 1 || InpSwLen15 < 1 || InpMaxZones < 1)
     {
      Print("Invalid inputs");
      return INIT_PARAMETERS_INCORRECT;
     }
   if(PeriodSeconds(InpBiasTF) <= PeriodSeconds(InpStructTF) || PeriodSeconds(InpStructTF) <= PeriodSeconds(InpEntryTF))
     {
      Print("Timeframes must satisfy: Bias > Structure > Entry");
      return INIT_PARAMETERS_INCORRECT;
     }
   if(InpBiasMode == BIAS_4H_PLUS_1H && (PeriodSeconds(InpBiasTF2) <= PeriodSeconds(InpStructTF) || PeriodSeconds(InpBiasTF2) >= PeriodSeconds(InpBiasTF)))
     {
      Print("Second bias timeframe must be above Structure and below the first bias timeframe");
      return INIT_PARAMETERS_INCORRECT;
     }
   ZeroMemory(g_bias);
   g_bias[0].tf = InpBiasTF;
   g_bias[1].tf = InpBiasTF2;
   g_biasCount  = (InpBiasMode == BIAS_4H_PLUS_1H) ? 2 : 1;
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(InpSlippage);
   trade.SetTypeFillingBySymbol(_Symbol);
   ArrayResize(g_zones, 0);
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason)
  {
   ObjectsDeleteAll(0, PFX);
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
      OnNewBar();
     }
   ManageZones();
  }
//+------------------------------------------------------------------+
