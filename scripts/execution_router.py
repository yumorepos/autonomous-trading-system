        """
        Route signal to appropriate executor.
        Returns: (exchange_name, live_mode, executor_or_adapter)
        """
        exchange = signal.get("exchange", "").lower()
        
        if "polymarket" in exchange:
            if self.pm_live and self.pm_executor:
                return "Polymarket", True, self.pm_executor
            else:
                adapter = get_paper_exchange_adapter("Polymarket")
                return "Polymarket", False, adapter
        
        elif "hyperliquid" in exchange:
            if self.hl_live:
                # Hyperliquid live executor not implemented yet
                print("[ROUTER] Hyperliquid live execution not implemented")
                adapter = get_paper_exchange_adapter("Hyperliquid")
                return "Hyperliquid", False, adapter
            else:
                adapter = get_paper_exchange_adapter("Hyperliquid")
                return "Hyperliquid", False, adapter
        
        else:
            # Default to Hyperliquid paper
            adapter = get_paper_exchange_adapter("Hyperliquid")
            return "Hyperliquid", False, adapter
    
    def execute_trade(self, signal: dict[str, Any]) -> dict[str, Any]:
        """Execute trade based on routing."""
        exchange, live_mode, executor = self.route_signal(signal)
        
        if live_mode:
            # Live execution
            if exchange == "Polymarket":
                # Polymarket live execution
                token_id = signal.get("market_id") or signal.get("asset", "")
                side = signal.get("direction", "").upper()
                size = signal.get("recommended_position_size_usd", 0)
                price = signal.get("entry_price", 0.5)
                
                return executor.execute_order(token_id, side, size, price)
            else:
                # Other live executors not implemented
                return {
                    "success": False,
                    "error": f"Live execution for {exchange} not implemented",
                    "exchange": exchange,
                }
        
        else:
            # Paper execution
            if PaperExchangeAdapter and isinstance(executor, PaperExchangeAdapter):
                # Paper exchange adapter
                try:
                    from scripts.phase1_paper_trader import PaperTradeEngine
                    position_id = f"paper-{exchange}-{int(os.urandom(4).hex())}"
                    
                    engine = PaperTradeEngine(
                        signal=signal,
                        position_id=position_id,
                        exchange=exchange
                    )
                    return engine.execute()
                except Exception as e:
                    return {
                        "success": False,
                        "error": str(e),
                        "exchange":exchange,
                    }
            else:
                return {
                    "success": False,
                    "error": f"No executor available for {exchange}",
                    "exchange": exchange,
                }


# Test the router
def test_routing() -> None:
    """Test execution routing."""
    router = ExecutionRouter(dry_run=True)
    
    test_signals = [
        {
            "exchange": "Polymarket",
            "market_id": "pm-btc-test",
            "asset": "pm-btc-test",
            "direction": "YES",
            "entry_price": 0.42,
            "recommended_position_size_usd": 3.0,
        },
        {
            "exchange": "Hyperliquid",
            "asset": "ETH",
            "direction": "LONG",
            "entry_price": 3500.0,
            "recommended_position_size_usd": 12.0,
        }
    ]
    
    for signal in test_signals:
        exchange, live_mode, executor = router.route_signal(signal)
        print(f"Signal {signal['asset']} → {exchange} (live={live_mode}, executor={executor})")
        
        result = router.execute_trade(signal)
        print(f"Result: {result.get('success', False)}")

if __name__ == "__main__":
    test_routing()