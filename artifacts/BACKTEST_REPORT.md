# Backtest Report

Generated: 2026-04-10 05:16 UTC
Period: 90 days | Initial capital: $1000

## Current Parameters

| Parameter | Value |
|-----------|-------|
| Stop Loss | -13% ROE |
| Take Profit | 13% ROE |
| Timeout | 8h |
| Trailing Activate | 2% ROE |
| Trailing Distance | 2% |

## Results

| Metric | Value |
|--------|-------|
| Total Trades | 61 |
| Wins / Losses | 41 / 20 |
| Win Rate | 67.2% |
| Gross PnL | $4.20 |
| Net PnL | $2.03 |
| Net Expectancy | $0.0333 / trade |
| Profit Factor | 1.08 |
| Sharpe Ratio | 0.91 |
| Max Drawdown | 0.95% |
| Final Capital | $1001.22 |

## Decision: CAUTIOUS (YELLOW)

Net expectancy $0.0333/trade — positive but below $0.30 confidence threshold

## Equity Curve

```
$ 1003.55 |                                                          *   
           |                                                        ** *  
           | *                                                    **      
           |  *                                           *             **
           |                            **               *  **  **        
           |   **                     **      **                          
           |*    **                          *         **  *              
           |       **                      **                 *           
$  998.04 |                              *                    *          
           |         *         *   ***          **   **                   
           |          **      *  **               ***                     
           |                                                              
           |             *   *                                            
           |            *   *   *                                         
           |                                                              
$  993.22 |              **                                              
           +--------------------------------------------------------------
            Trade 1                                               Trade 61
```

## Equity Data Points

| Trade # | Capital |
|---------|---------|
| 1 | $1002.56 |
| 2 | $1001.54 |
| 3 | $1000.28 |
| 4 | $1000.65 |
| 5 | $999.59 |
| 6 | $999.69 |
| 7 | $998.90 |
| 8 | $998.93 |
| 9 | $997.47 |
| 10 | $996.82 |
| 11 | $997.12 |
| 12 | $995.09 |
| 13 | $995.86 |
| 14 | $993.22 |
| 15 | $993.66 |
| 16 | $994.62 |
| 17 | $995.67 |
| 18 | $996.75 |
| 19 | $997.71 |
| 20 | $995.07 |
| 21 | $996.71 |
| 24 | $997.61 |
| 27 | $1000.65 |
| 30 | $998.61 |
| 33 | $999.73 |
| 36 | $997.88 |
| 39 | $997.03 |
| 42 | $997.61 |
| 45 | $1000.98 |
| 48 | $1000.85 |
| 51 | $998.30 |
| 54 | $1002.18 |
| 57 | $1003.01 |
| 60 | $1001.97 |
| 61 | $1002.03 |

## Top 5 Parameter Combinations (from sweep)

| Rank | Stop Loss | Take Profit | Net Exp/Trade | Win Rate | Sharpe | Trades | Max DD |
|------|-----------|-------------|---------------|----------|--------|--------|--------|
| 1 | -15% | +13% | $0.0789 | 69% | 2.14 | 55 | 0.57% |
| 2 | -11% | +13% | $0.0777 | 69% | 2.16 | 55 | 0.72% |
| 3 | -15% | +15% | $0.0742 | 69% | 2.03 | 55 | 0.57% |
| 4 | -11% | +15% | $0.0731 | 69% | 2.04 | 55 | 0.72% |
| 5 | -15% | +17% | $0.0725 | 69% | 1.99 | 55 | 0.57% |
