"""
MAT8 Performance Sync — CM Series
Fetches live IBKR account data via Flex Web Service API,
excludes the IBKR gifted share from all calculations,
and writes performance_data.json for the dashboard.

Place this file at the root of the CM-Returns GitHub repo.
GitHub Actions runs it daily via sync.yml.
"""

import os
import json
import time
import datetime
import xml.etree.ElementTree as ET
import urllib.request
import urllib.parse
import urllib.error

# ── Configuration ─────────────────────────────────────────────────────────────
STRATEGY_NAME        = "CM"                    # Change to "LML" in the LML repo
FLEX_TOKEN           = os.environ["IBKR_FLEX_TOKEN"]
FLEX_QUERY_ID        = os.environ["IBKR_QUERY_ID"]
STARTING_BALANCE     = float(os.environ.get("STARTING_BALANCE", "10000.00"))

# Symbols to completely exclude from all calculations
EXCLUDED_SYMBOLS     = {"IBKR"}               # IBKR gifted share — excluded

OUTPUT_PATH          = "data/performance_data.json"

# IBKR Flex Web Service endpoints
SEND_URL = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/SendRequest"
GET_URL  = "https://gdcdyn.interactivebrokers.com/AccountManagement/FlexWebService/GetStatement"
FLEX_VER = "3"

# ── Step 1: Request the Flex Statement ────────────────────────────────────────
def request_flex_statement():
    params = urllib.parse.urlencode({
        "t": FLEX_TOKEN,
        "q": FLEX_QUERY_ID,
        "v": FLEX_VER,
    })
    url = f"{SEND_URL}?{params}"
    print(f"Requesting Flex statement... Query ID: {FLEX_QUERY_ID}")

    with urllib.request.urlopen(url, timeout=30) as resp:
        raw = resp.read().decode("utf-8")

    root = ET.fromstring(raw)

    # Check for errors
    status = root.find(".//Status")
    if status is not None and status.text and status.text.strip() != "Success":
        error = root.find(".//ErrorMessage")
        msg   = error.text if error is not None else raw
        raise RuntimeError(f"IBKR SendRequest error: {msg}")

    ref = root.find(".//ReferenceCode")
    if ref is None or not ref.text:
        raise RuntimeError(f"No ReferenceCode in response: {raw}")

    code = ref.text.strip()
    print(f"Reference code received: {code}")
    return code


# ── Step 2: Poll until the statement is ready ─────────────────────────────────
def fetch_flex_statement(ref_code, max_retries=10, wait_sec=10):
    for attempt in range(1, max_retries + 1):
        print(f"Fetching statement (attempt {attempt}/{max_retries})...")
        time.sleep(wait_sec)

        params = urllib.parse.urlencode({
            "t": FLEX_TOKEN,
            "q": ref_code,
            "v": FLEX_VER,
        })
        url = f"{GET_URL}?{params}"

        with urllib.request.urlopen(url, timeout=30) as resp:
            raw = resp.read().decode("utf-8")

        # If it's XML starting with FlexQueryResponse it's ready
        if raw.strip().startswith("<?xml") or raw.strip().startswith("<FlexQueryResponse"):
            root = ET.fromstring(raw)

            # Check if still pending
            status = root.find(".//Status")
            if status is not None and status.text:
                txt = status.text.strip()
                if txt in ("Statement generation in progress.", "Please wait"):
                    print(f"  Still generating... waiting {wait_sec}s")
                    continue
                if txt not in ("Success", ""):
                    error = root.find(".//ErrorMessage")
                    msg   = error.text if error is not None else txt
                    raise RuntimeError(f"IBKR GetStatement error: {msg}")

            print("Statement ready.")
            return root

    raise RuntimeError(f"Statement not ready after {max_retries} attempts.")


# ── Step 3: Parse trades — exclude IBKR symbol ────────────────────────────────
def parse_trades(root):
    trades = []
    for t in root.findall(".//Trade"):
        sym  = (t.get("symbol") or "").strip().upper()
        if sym in EXCLUDED_SYMBOLS:
            print(f"  Skipping excluded symbol: {sym}")
            continue

        # Only closed trades (buySell="BUY"/"SELL" with a realizedPnL)
        pnl_str = t.get("fifoPnlRealized") or t.get("realizedPnL") or "0"
        try:
            pnl = float(pnl_str)
        except ValueError:
            continue

        # Skip opening legs (no realised P&L yet)
        open_close = (t.get("openCloseIndicator") or "").upper()
        if open_close == "O":
            continue

        comm_str = t.get("ibCommission") or t.get("commission") or "0"
        try:
            comm = float(comm_str)
        except ValueError:
            comm = 0.0

        net_pnl = pnl + comm  # commission is already negative in IBKR data

        date_str = t.get("tradeDate") or t.get("dateTime", "")[:8]
        trades.append({
            "date":    date_str,
            "symbol":  sym,
            "pnl":     net_pnl,
            "won":     net_pnl > 0,
        })

    print(f"Parsed {len(trades)} closed trades (IBKR symbol excluded)")
    return trades


# ── Step 4: Parse equity curve from EquitySummaryByReportDateInBase ───────────
def parse_equity_curve(root):
    """
    Reads EquitySummaryByReportDateInBase entries.
    Excludes value of IBKR gifted share from each day's balance.
    """
    # Build a map of date → IBKR stock value (to subtract)
    ibkr_daily_value = {}
    for pos in root.findall(".//OpenPosition"):
        sym = (pos.get("symbol") or "").strip().upper()
        if sym in EXCLUDED_SYMBOLS:
            report_date = pos.get("reportDate") or ""
            mkt_val_str = pos.get("positionValue") or pos.get("markPrice") or "0"
            qty_str     = pos.get("position") or "1"
            try:
                mkt_val = float(mkt_val_str)
                # If only markPrice given, multiply by qty
                if pos.get("positionValue") is None:
                    mkt_val = float(mkt_val_str) * float(qty_str)
                ibkr_daily_value[report_date] = mkt_val
                print(f"  IBKR gifted share value on {report_date}: ${mkt_val:.2f} (will be excluded)")
            except ValueError:
                pass

    # Also check MarkToMarket for daily IBKR values
    for mtm in root.findall(".//MarkToMarketPerformanceSummaryUnderlying"):
        sym = (mtm.get("symbol") or "").strip().upper()
        if sym in EXCLUDED_SYMBOLS:
            date_str = mtm.get("reportDate") or ""
            val_str  = mtm.get("endingValue") or "0"
            try:
                ibkr_daily_value[date_str] = float(val_str)
            except ValueError:
                pass

    # Parse daily equity totals
    equity_points = []
    for eq in root.findall(".//EquitySummaryByReportDateInBase"):
        date_str = eq.get("reportDate") or ""
        if not date_str:
            continue

        total_str = (
            eq.get("total") or
            eq.get("totalLong") or
            eq.get("endingEquity") or
            "0"
        )
        try:
            total = float(total_str)
        except ValueError:
            continue

        # Subtract excluded symbol value
        excluded_val = ibkr_daily_value.get(date_str, 0.0)
        adjusted     = total - excluded_val

        equity_points.append({
            "date":    date_str,
            "balance": round(adjusted, 2),
        })

    # Sort by date
    equity_points.sort(key=lambda x: x["date"])

    # Compute daily P&L
    prev_balance = STARTING_BALANCE
    curve = []
    for pt in equity_points:
        daily_pnl = round(pt["balance"] - prev_balance, 2)
        curve.append({
            "date":      pt["date"],
            "balance":   pt["balance"],
            "daily_pnl": daily_pnl,
        })
        prev_balance = pt["balance"]

    print(f"Equity curve: {len(curve)} data points")
    return curve


# ── Step 4b: Capture value of currently OPEN (unclosed) positions ─────────────
def get_open_positions_summary(root):
    """
    Reads the OpenPosition section — IBKR's live snapshot of current holdings —
    and sums their mark-to-market value, excluding any symbol in EXCLUDED_SYMBOLS
    (e.g. the gifted IBKR share).

    This exists because EquitySummaryByReportDateInBase carries a built-in
    one-day reporting lag: a position opened today won't be reflected in the
    official daily NAV total until tomorrow's statement. Reading OpenPosition
    directly lets us value still-open trades using their latest known mark
    price, so the equity curve doesn't show a gap or flat day while a trade
    is active.
    """
    positions = []
    for pos in root.findall(".//OpenPosition"):
        sym = (pos.get("symbol") or "").strip().upper()
        if sym in EXCLUDED_SYMBOLS:
            continue

        report_date = pos.get("reportDate") or ""
        val_str = pos.get("positionValue")
        if val_str is not None:
            try:
                val = float(val_str)
            except ValueError:
                val = 0.0
        else:
            qty_str  = pos.get("position")  or "0"
            mark_str = pos.get("markPrice") or "0"
            try:
                val = float(qty_str) * float(mark_str)
            except ValueError:
                val = 0.0

        positions.append({"symbol": sym, "value": val, "report_date": report_date})

    total_value = sum(p["value"] for p in positions)
    latest_date = max((p["report_date"] for p in positions if p["report_date"]), default=None)

    if positions:
        print(f"  Open positions (excl. excluded symbols): {len(positions)} "
              f"({', '.join(p['symbol'] for p in positions)}), "
              f"total mark-to-market value: ${total_value:.2f}, as of {latest_date}")
    else:
        print("  No currently open positions found.")

    return total_value, latest_date


def apply_open_position_value(equity_curve, open_value, open_date):
    """
    Ensures the equity curve reflects the current value of open (unclosed)
    positions, instead of that value being missing until the trade closes.

    - If open_date matches the latest equity curve entry's date, the open
      position value is added directly into that entry (it's part of that
      day's true total value, just not yet reflected in the official NAV
      total at the time the report was generated).
    - If open_date is MORE RECENT than the latest equity curve entry (i.e.
      the trade opened on a day not yet covered by an official EquitySummary
      entry), a new entry is appended for that date so the open trade's
      value isn't simply absent from the chart while it's still active.
    """
    if not equity_curve or open_value == 0 or open_date is None:
        return equity_curve

    last = equity_curve[-1]

    if open_date == last["date"]:
        prev_balance = equity_curve[-2]["balance"] if len(equity_curve) > 1 else STARTING_BALANCE
        last["balance"] = round(last["balance"] + open_value, 2)
        last["daily_pnl"] = round(last["balance"] - prev_balance, 2)
        print(f"  Added open position value ${open_value:.2f} into existing entry for {last['date']}")
    elif open_date > last["date"]:
        new_balance = round(last["balance"] + open_value, 2)
        equity_curve.append({
            "date":      open_date,
            "balance":   new_balance,
            "daily_pnl": round(new_balance - last["balance"], 2),
        })
        print(f"  Appended new entry for {open_date} including open position value ${open_value:.2f}")

    return equity_curve


# ── Step 5: Build metrics from trades and equity curve ────────────────────────
def build_metrics(trades, equity_curve):
    total_trades   = len(trades)
    winning_trades = sum(1 for t in trades if t["won"])
    losing_trades  = total_trades - winning_trades
    win_rate_pct   = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0

    gross_profit = sum(t["pnl"] for t in trades if t["pnl"] > 0)
    gross_loss   = abs(sum(t["pnl"] for t in trades if t["pnl"] < 0))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 0.0

    ending_balance   = equity_curve[-1]["balance"] if equity_curve else STARTING_BALANCE
    total_return_pct = ((ending_balance - STARTING_BALANCE) / STARTING_BALANCE * 100)

    # Max drawdown
    peak = STARTING_BALANCE
    max_dd = 0.0
    for pt in equity_curve:
        bal = pt["balance"]
        if bal > peak:
            peak = bal
        dd = (peak - bal) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

    # Sharpe (simplified annualised daily returns)
    daily_pnls = [pt["daily_pnl"] for pt in equity_curve if pt["daily_pnl"] != 0]
    sharpe = 0.0
    if len(daily_pnls) > 1:
        import statistics
        mean_pnl = statistics.mean(daily_pnls)
        std_pnl  = statistics.stdev(daily_pnls)
        if std_pnl > 0:
            sharpe = round((mean_pnl / std_pnl) * (252 ** 0.5), 2)

    return {
        "starting_balance":  round(STARTING_BALANCE, 2),
        "ending_balance":    round(ending_balance, 2),
        "total_return_pct":  round(total_return_pct, 2),
        "max_drawdown_pct":  round(max_dd, 2),
        "sharpe_ratio":      sharpe,
        "profit_factor":     round(profit_factor, 2),
        "win_rate_pct":      round(win_rate_pct, 2),
        "total_trades":      total_trades,
        "winning_trades":    winning_trades,
        "losing_trades":     losing_trades,
    }


# ── Step 6: Write JSON output ──────────────────────────────────────────────────
def write_output(metrics, equity_curve):
    os.makedirs("data", exist_ok=True)
    payload = {
        "strategy":    STRATEGY_NAME,
        "last_updated": datetime.date.today().isoformat(),
        "metrics":     metrics,
        "equity_curve": equity_curve,
        "excluded_symbols": list(EXCLUDED_SYMBOLS),
    }
    with open(OUTPUT_PATH, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"Written: {OUTPUT_PATH}")
    print(f"  Strategy:       {STRATEGY_NAME}")
    print(f"  Trades:         {metrics['total_trades']}")
    print(f"  Total Return:   {metrics['total_return_pct']:.2f}%")
    print(f"  Max Drawdown:   {metrics['max_drawdown_pct']:.2f}%")
    print(f"  Sharpe:         {metrics['sharpe_ratio']}")
    print(f"  Excluded:       {list(EXCLUDED_SYMBOLS)}")


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    print(f"=== MAT8 Performance Sync: {STRATEGY_NAME} ===")
    print(f"Excluded symbols: {EXCLUDED_SYMBOLS}")
    print()

    ref_code     = request_flex_statement()
    root         = fetch_flex_statement(ref_code)

    trades       = parse_trades(root)
    equity_curve = parse_equity_curve(root)

    if not equity_curve:
        print("WARNING: No equity curve data found. Check Flex Query sections.")
        equity_curve = [{
            "date":      datetime.date.today().isoformat(),
            "balance":   STARTING_BALANCE,
            "daily_pnl": 0.0,
        }]

    # Add in the current value of any still-open (unclosed) positions, so the
    # latest data point reflects total estimated value, not just closed trades.
    open_value, open_date = get_open_positions_summary(root)
    equity_curve = apply_open_position_value(equity_curve, open_value, open_date)

    metrics = build_metrics(trades, equity_curve)
    write_output(metrics, equity_curve)
    print("\nSync complete.")


if __name__ == "__main__":
    main()
