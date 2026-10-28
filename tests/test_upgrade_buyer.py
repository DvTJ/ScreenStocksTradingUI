"""The bot's upgrade purchases (screenstocks/upgrade_buyer.py): valuation, limits and budget."""

from screenstocks import upgrade_buyer as ub
from screenstocks.bot import BotSettings

# the live catalog of 28 Oct 2026 (cash 134 B, dividends 11.9 M/min)
CATALOG = [
    {"upgradeId": "BuyCooldown", "currentLevel": 78, "maxed": False, "currentValue": 91, "nextValue": 90.5, "nextPrice": "385968164216.36"},
    {"upgradeId": "ShortCooldown", "currentLevel": 62, "maxed": False, "currentValue": 104, "nextValue": 103.5, "nextPrice": "5800398710.97"},
    {"upgradeId": "AutoActionCooldown", "currentLevel": 1, "maxed": False, "currentValue": 224, "nextValue": 223, "nextPrice": "1300"},
    {"upgradeId": "IncomePerMinute", "currentLevel": 0, "maxed": False, "currentValue": 10, "nextValue": 80, "nextPrice": "100"},
    {"upgradeId": "OfflineEarnings", "currentLevel": 12, "maxed": False, "currentValue": 21, "nextValue": 21.5, "nextPrice": "398580750"},
    {"upgradeId": "DividendGain", "currentLevel": 8, "maxed": False, "currentValue": 55, "nextValue": 60, "nextPrice": "140800"},
    {"upgradeId": "OfflineHours", "currentLevel": 10, "maxed": False, "currentValue": 5.75, "nextValue": 5.85, "nextPrice": "59049000"},
    {"upgradeId": "StockVolume", "currentLevel": 0, "maxed": False, "currentValue": 0, "nextValue": 15, "nextPrice": "550"},
]
PROFIT = {"long": 6e8, "short": 3.8e8}


def test_values_what_helps_the_bot_and_nothing_else():
    pick, rows = ub.choose(CATALOG, 1e12, 11.9e6, PROFIT, True, 1.0, 60)
    ids = [r["id"] for r in rows]
    assert pick["id"] == "StockVolume"
    assert set(ids) == {"StockVolume", "DividendGain", "IncomePerMinute", "ShortCooldown", "BuyCooldown"}
    by = {r["id"]: r for r in rows}
    assert abs(by["IncomePerMinute"]["gain"] - 70) < 1e-9
    assert abs(by["DividendGain"]["gain"] - 11.9e6 * (160 / 155 - 1)) < 1
    assert by["BuyCooldown"]["payback"] > 60 * 24, "a cooldown level for 386 B is not worth it"


def test_limits_payback_budget_and_declined():
    pick, _ = ub.choose(CATALOG, 1e12, 11.9e6, PROFIT, True, 1.0, 60, skip={"StockVolume"})
    assert pick["id"] == "DividendGain"
    pick, _ = ub.choose(CATALOG, 99.0, 11.9e6, PROFIT, True, 1.0, 60)
    assert pick is None, "nothing fits a budget of 99"
    expensive = [dict(u, nextPrice="1e15") for u in CATALOG]
    assert ub.choose(expensive, 1e20, 11.9e6, PROFIT, True, 1.0, 60)[0] is None, "payback limit"


def test_unproven_bot_values_only_income_and_dividends():
    pick, rows = ub.choose(CATALOG, 1e12, 11.9e6, {"long": 0.0, "short": 0.0}, True, 1.0, 60)
    assert {r["id"] for r in rows} == {"DividendGain", "IncomePerMinute"}
    _, rows = ub.choose(CATALOG, 1e12, 11.9e6, PROFIT, False, 1.0, 60)
    assert "ShortCooldown" not in {r["id"] for r in rows}, "no shorts, no short cooldown"
    _, rows = ub.choose(CATALOG, 1e12, 11.9e6, PROFIT, True, 0.0, 60)
    assert "StockVolume" not in {r["id"] for r in rows}, "volume that caps nothing is worth nothing"


def test_profit_needs_trades_and_time():
    since = 1_000_000
    now = since + 100 * 60000
    trades = [{"side": "long", "ret": 2.0, "money": 1000} for _ in range(5)]
    assert ub.profit_per_min({"since": since, "trades": trades}, now)["long"] == 100 / 100   # 5 x 20 in 100 min
    assert ub.profit_per_min({"since": since, "trades": trades[:4]}, now)["long"] == 0
    assert ub.profit_per_min({"since": now - 60000, "trades": trades}, now)["long"] == 0
    losing = [dict(x, ret=-2.0) for x in trades]
    assert ub.profit_per_min({"since": since, "trades": losing}, now)["long"] == 0


def test_volume_capped_and_hourly_budget():
    stocks = [{"unlocked": True, "price": 10, "availableShares": 100}, {"unlocked": True, "price": 10, "availableShares": 10**9},
              {"unlocked": False, "price": 10, "availableShares": 0}]
    assert ub.volume_capped(stocks, 10000, 25) == 0.5
    buyer = ub.UpgradeBuyer(":memory:")
    buyer._spent = [(1000.0, 30.0), (0.0, 50.0)]
    assert buyer.budget(1000, 5.0, 3601.0) == 50 - 30, "purchases older than an hour no longer count"


def test_settings_default_off_and_clamped():
    s = BotSettings()
    assert not s.buy_upgrades and s.upgrade_payback_min == 60 and s.upgrade_max_pct == 5
    s = BotSettings(upgrade_payback_min=-3, upgrade_max_pct=500)
    assert s.upgrade_payback_min == 1 and s.upgrade_max_pct == 100


def test_paper_mode_and_switched_off_never_check():
    buyer = ub.UpgradeBuyer(":memory:")
    for s in (BotSettings(enabled=True, buy_upgrades=True, paper=True), BotSettings(enabled=True), BotSettings(buy_upgrades=True)):
        buyer.step(s, True, False)
        assert not buyer._busy
    buyer.step(BotSettings(enabled=True, buy_upgrades=True), True, True)
    assert not buyer._busy, "not after the loss limit"
