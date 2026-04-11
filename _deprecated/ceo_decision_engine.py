#!/usr/bin/env python3
"""
CEO Decision Engine: Automated decision-making based on daily update data.
Enforces actions based on validation state, preserving discipline lock rules.
"""

import json
from pathlib import Path
from datetime import datetime, timezone

# Import daily_update logic
import sys
sys.path.insert(0, str(Path(__file__).parent))
from daily_update import get_current_capital, get_trade_stats

# Thresholds
VALIDATION_TRADES = 20
STRONG_EDGE_EXPECTANCY = 0.50
STRONG_EDGE_WIN_RATE = 0.50
WEAK_EDGE_EXPECTANCY = 0.0
WEAK_EDGE_WIN_RATE = 0.45
CIRCUIT_BREAKER_DRAWDOWN = 0.20  # 20% from peak

class CEODecisionEngine:
    """Automated decision engine for 30-day challenge."""
    
    def __init__(self):
        self.stats = get_trade_stats()
        self.capital = get_current_capital()
        self.start_capital = 97.14
        self.peak_capital = max(self.capital or self.start_capital, self.start_capital)
    
    def assess_validation_state(self):
        """Determine if edge is validated, weak, or not proven."""
        if self.stats['closed'] < VALIDATION_TRADES:
            return "IN_PROGRESS"
        
        exp = self.stats['expectancy']
        wr = self.stats['win_rate']
        
        if exp >= STRONG_EDGE_EXPECTANCY and wr >= STRONG_EDGE_WIN_RATE:
            return "VALIDATED"
        elif exp >= WEAK_EDGE_EXPECTANCY and wr >= WEAK_EDGE_WIN_RATE:
            return "WEAK_EDGE"
        else:
            return "NO_EDGE"
    
    def check_circuit_breakers(self):
        """Check if any circuit breakers should trip."""
        if not self.capital:
            return None
        
        drawdown = (self.peak_capital - self.capital) / self.peak_capital
        
        if drawdown >= CIRCUIT_BREAKER_DRAWDOWN:
            return "DRAWDOWN_HALT"
        
        # Check for consecutive losses (would need trade sequence data)
        # Check for daily loss >$10 (would need daily P&L tracking)
        # These are handled by risk_guardian.py
        
        return None
    
    def recommend_action(self):
        """Determine recommended action based on current state."""
        state = self.assess_validation_state()
        breaker = self.check_circuit_breakers()
        
        if breaker:
            return {
                "action": "HALT",
                "reason": f"Circuit breaker: {breaker}",
                "automated": True,
                "requires_approval": False,
            }
        
        if state == "IN_PROGRESS":
            return {
                "action": "HOLD",
                "reason": f"Validation in progress ({self.stats['closed']}/{VALIDATION_TRADES} trades)",
                "automated": True,
                "requires_approval": False,
            }
        
        elif state == "VALIDATED":
            return {
                "action": "SCALE",
                "reason": f"Edge validated (exp=${self.stats['expectancy']:.2f}, WR={self.stats['win_rate']*100:.1f}%)",
                "details": "Increase Tier 1: $15→$18, Tier 2: $8→$10, unlock optimization",
                "automated": True,
                "requires_approval": False,
            }
        
        elif state == "WEAK_EDGE":
            return {
                "action": "HOLD",
                "reason": f"Weak edge detected (exp=${self.stats['expectancy']:.2f}, WR={self.stats['win_rate']*100:.1f}%)",
                "details": "Continue at current sizing, accumulate 10 more trades for analysis",
                "automated": True,
                "requires_approval": False,
            }
        
        elif state == "NO_EDGE":
            return {
                "action": "REVIEW",
                "reason": f"No edge found (exp=${self.stats['expectancy']:.2f}, WR={self.stats['win_rate']*100:.1f}%)",
                "details": "Strategy not working, recommend manual review and potential pivot",
                "automated": False,
                "requires_approval": True,
            }
    
    def execute_action(self, action_plan):
        """Execute automated actions (where permitted)."""
        action = action_plan["action"]
        
        if not action_plan["automated"]:
            return {
                "executed": False,
                "reason": "Requires manual approval",
                "recommendation": action_plan,
            }
        
        if action == "HOLD":
            return {
                "executed": True,
                "action": "HOLD",
                "message": "System continues autonomously, no changes",
            }
        
        elif action == "SCALE":
            # Auto-execute scaling (update tiered_scanner.py thresholds)
            return self._execute_scaling(action_plan)
        
        elif action == "HALT":
            # Auto-execute halt (set ENTRY_MODE=paper or similar)
            return self._execute_halt(action_plan)
        
        else:
            return {
                "executed": False,
                "reason": "Unknown action",
            }
    
    def _execute_scaling(self, plan):
        """Execute position size scaling."""
        # Update TIER1_POSITION_SIZE and TIER2_POSITION_SIZE in tiered_scanner.py
        scanner_file = Path(__file__).parent / "tiered_scanner.py"
        
        if not scanner_file.exists():
            return {"executed": False, "reason": "Scanner file not found"}
        
        content = scanner_file.read_text()
        
        # Update Tier 1: $15 → $18
        content = content.replace(
            "TIER1_POSITION_SIZE = 15.0",
            "TIER1_POSITION_SIZE = 18.0"
        )
        
        # Update Tier 2: $8 → $10
        content = content.replace(
            "TIER2_POSITION_SIZE = 8.0",
            "TIER2_POSITION_SIZE = 10.0"
        )
        
        scanner_file.write_text(content)
        
        return {
            "executed": True,
            "action": "SCALE",
            "message": "Position sizes increased: Tier 1 $15→$18, Tier 2 $8→$10",
            "file_modified": str(scanner_file),
        }
    
    def _execute_halt(self, plan):
        """Execute system halt."""
        # This would typically set a flag or modify config
        # For now, just return notification
        return {
            "executed": False,
            "action": "HALT",
            "message": "CIRCUIT BREAKER TRIPPED — Manual review required",
            "reason": plan["reason"],
        }
    
    def generate_report(self):
        """Generate decision report."""
        action_plan = self.recommend_action()
        execution_result = self.execute_action(action_plan)
        
        print("=" * 70)
        print("  CEO DECISION ENGINE")
        print("  " + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
        print("=" * 70)
        print()
        
        # Current State
        print("CURRENT STATE:")
        print(f"  Capital: ${self.capital:.2f}" if self.capital else "  Capital: Unable to fetch")
        print(f"  Closed Trades: {self.stats['closed']} / {VALIDATION_TRADES}")
        
        if self.stats['closed'] > 0:
            print(f"  Win Rate: {self.stats['win_rate']*100:.1f}%")
            print(f"  Expectancy: ${self.stats['expectancy']:+.2f}/trade")
        
        print()
        
        # Validation State
        state = self.assess_validation_state()
        print(f"VALIDATION STATE: {state}")
        print()
        
        # Recommended Action
        print("RECOMMENDED ACTION:")
        print(f"  Action: {action_plan['action']}")
        print(f"  Reason: {action_plan['reason']}")
        
        if 'details' in action_plan:
            print(f"  Details: {action_plan['details']}")
        
        print(f"  Automated: {'YES' if action_plan['automated'] else 'NO (requires approval)'}")
        print()
        
        # Execution Result
        print("EXECUTION:")
        if execution_result['executed']:
            print(f"  ✅ {execution_result['message']}")
            if 'file_modified' in execution_result:
                print(f"  File modified: {execution_result['file_modified']}")
        else:
            print(f"  ⏸️  Not executed: {execution_result['reason']}")
            if 'recommendation' in execution_result:
                print(f"  Recommendation: {execution_result['recommendation']}")
        
        print()
        print("=" * 70)
        
        return {
            "state": state,
            "action_plan": action_plan,
            "execution": execution_result,
        }

if __name__ == "__main__":
    engine = CEODecisionEngine()
    engine.generate_report()
