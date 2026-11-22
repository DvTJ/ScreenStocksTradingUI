from screenstocks import automation_setups as setups, bot
from screenstocks.storage import Storage


def test_switches_thresholds_and_manual_presets_and_resets_after_ipo(tmp_path):
    db = Storage(tmp_path / "history.db")
    try:
        bot.save_settings(db, bot.BotSettings(enabled=True, trade_pct=22))
        setups.save_profile(db, "Start", "0", True, None)
        bot.save_settings(db, bot.BotSettings(enabled=False, trade_pct=100))
        setups.save_profile(db, "Above", "1Qi", True, None)
        bot.save_settings(db, bot.BotSettings(enabled=True, trade_pct=55))
        setups.save_profile(db, "Manual", "", True, None)
        cfg = setups.config(db)
        cfg.update(enabled=True, switch_back=False, metric="cash")
        setups.save(db, setups.CONFIG, cfg)
        app = setups.SetupSwitcher(db.path)

        def evaluate(cash, ipo=0):
            app._evaluate(db, {"cash": cash, "net_worth": 1e24, "ipo_count": ipo})
            return bot.load_settings(db)

        assert evaluate(5).trade_pct == 22
        settings = evaluate(1e18)
        assert settings.trade_pct == 100 and not settings.enabled
        assert evaluate(5).trade_pct == 100
        assert evaluate(5, ipo=1).trade_pct == 22
        setups.save(db, setups.MANUAL, {"id": "apply-manual", "name": "Manual"})
        assert evaluate(5, ipo=1).trade_pct == 55
        assert evaluate(7, ipo=1).trade_pct == 55
        assert evaluate(1e18, ipo=1).trade_pct == 100
        cfg["switch_back"] = True
        setups.save(db, setups.CONFIG, cfg)
        assert evaluate(7, ipo=1).trade_pct == 22
    finally:
        db.close()


def test_apply_actions_reuses_slots_and_disables_surplus():
    action = {"stockId": "$BASE", "actionType": "Buy", "condition": "Below",
              "targetPrice": 200, "amountPercentage": 100, "enabled": True}

    class Bridge:
        def __init__(self):
            self.calls = []

        def request(self, method, params=None):
            self.calls.append((method, params))
            if method == "auto_actions.snapshot":
                return {"unlocked": True, "slotLimit": 2, "active": True, "actions": [
                    {**action, "slotIndex": 0}, {**action, "slotIndex": 1, "stockId": "$MOVE"},
                ]}

    bridge = Bridge()
    setups.apply_actions(bridge, {"active": True, "actions": [action]})
    assert bridge.calls == [
        ("auto_actions.snapshot", None),
        ("auto_actions.set_active", {"active": False}),
        ("auto_actions.set_enabled", {"slotIndex": 1, "enabled": False}),
        ("auto_actions.set_active", {"active": True}),
    ]
