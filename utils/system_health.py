from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from config.runtime import LOGS_DIR, WORKSPACE_ROOT
from utils.json_utils import safe_read_json, safe_read_jsonl, write_json_atomic

SYSTEM_HEALTH_FILE = WORKSPACE_ROOT / "system_health.json"
SYSTEM_INCIDENTS_LOG = LOGS_DIR / "system-incidents.jsonl"

HEALTHY = "HEALTHY"
DEGRADED = "DEGRADED"
CRITICAL = "CRITICAL"

SEVERITY_LEVELS = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
SEVERITY_RANK = {severity: index for index, severity in enumerate(SEVERITY_LEVELS, start=1)}

ROLLING_WINDOW = timedelta(hours=6)
ESCALATION_WINDOW = timedelta(hours=1)
LOW_TO_MEDIUM_COUNT = 3
MEDIUM_TO_HIGH_COUNT = 3


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SystemHealthManager:
    """Central health-state manager for incidents, escalation, and trading response."""

    def __init__(self):
        self.health_file = SYSTEM_HEALTH_FILE
        self.incidents_log = SYSTEM_INCIDENTS_LOG
        if not self.health_file.exists():
            self.save_state(self.default_state())

    def default_state(self) -> dict[str, Any]:
        return {
            "overall_status": HEALTHY,
            "active_incidents": [],
            "last_updated": utc_now().isoformat(),
            "affected_components": [],
        }

    def load_state(self) -> dict[str, Any]:
        return safe_read_json(self.health_file) or self.default_state()

    def save_state(self, state: dict[str, Any]) -> None:
        write_json_atomic(self.health_file, state)

    def _append_incident(self, incident: dict[str, Any]) -> None:
        self.incidents_log.parent.mkdir(parents=True, exist_ok=True)
        with open(self.incidents_log, "a") as handle:
            handle.write(json.dumps(incident) + "\n")

    def _parse_timestamp(self, timestamp: str | None) -> datetime | None:
        if not timestamp:
            return None
        try:
            return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            return None

    def _recent_incidents(
        self,
        *,
        window: timedelta = ROLLING_WINDOW,
        incident_type: str | None = None,
        source: str | None = None,
        severity: str | None = None,
    ) -> list[dict[str, Any]]:
        cutoff = utc_now() - window
        recent: list[dict[str, Any]] = []
        for incident in safe_read_jsonl(self.incidents_log):
            incident_time = self._parse_timestamp(incident.get("timestamp"))
            if incident_time is None or incident_time < cutoff:
                continue
            if incident_type and incident.get("type") != incident_type:
                continue
            if source and incident.get("source") != source:
                continue
            if severity and incident.get("severity") != severity:
                continue
            recent.append(incident)
        return recent

    def _escalate_severity(self, severity: str, incident_type: str, source: str) -> tuple[str, str | None]:
        normalized = severity.upper()
        if normalized not in SEVERITY_RANK:
            normalized = "LOW"

        if normalized == "LOW":
            low_incidents = self._recent_incidents(
                window=ESCALATION_WINDOW,
                incident_type=incident_type,
                source=source,
                severity="LOW",
            )
            if len(low_incidents) >= LOW_TO_MEDIUM_COUNT - 1:
                return "MEDIUM", "Repeated LOW incidents escalated to MEDIUM"

        if normalized == "MEDIUM":
            medium_incidents = self._recent_incidents(
                window=ESCALATION_WINDOW,
                incident_type=incident_type,
                source=source,
                severity="MEDIUM",
            )
            if len(medium_incidents) >= MEDIUM_TO_HIGH_COUNT - 1:
                return "HIGH", "Repeated MEDIUM incidents escalated to HIGH"

        return normalized, None

    def refresh_state(self) -> dict[str, Any]:
        active_incidents = self._recent_incidents()
        affected_components = sorted(
            {
                component
                for incident in active_incidents
                for component in incident.get("affected_components", [])
                if component
            }
        )

        if any(incident.get("severity") == "CRITICAL" for incident in active_incidents):
            overall_status = CRITICAL
        elif active_incidents:
            overall_status = DEGRADED
        else:
            overall_status = HEALTHY

        state = {
            "overall_status": overall_status,
            "active_incidents": active_incidents[-25:],
            "last_updated": utc_now().isoformat(),
            "affected_components": affected_components,
        }
        self.save_state(state)
        return state

    def record_incident(
        self,
        *,
        incident_type: str,
        severity: str,
        source: str,
        message: str,
        affected_trade: str | None = None,
        affected_system: str | None = None,
        affected_components: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        escalated_severity, escalation_reason = self._escalate_severity(severity, incident_type, source)
        timestamp = utc_now().isoformat()
        incident = {
            "type": incident_type,
            "severity": escalated_severity,
            "timestamp": timestamp,
            "source": source,
            "message": message,
            "affected_trade": affected_trade,
            "affected_system": affected_system or "trading-system",
            "affected_components": affected_components or [],
            "metadata": metadata or {},
        }
        if escalation_reason:
            incident["metadata"]["escalation_reason"] = escalation_reason

        self._append_incident(incident)
        state = self.refresh_state()
        return {"incident": incident, "state": state}

    def trading_response(self) -> dict[str, Any]:
        state = self.refresh_state()
        status = state["overall_status"]
        active_incidents = state.get("active_incidents", [])

        if status == CRITICAL:
            return {
                "overall_status": status,
                "allow_new_trades": False,
                "allow_monitoring": True,
                "allow_exits": True,
                "action": "HALT_NEW_TRADES",
                "reason": (
                    active_incidents[-1]["message"]
                    if active_incidents
                    else "Critical system health state"
                ),
            }

        if status == DEGRADED:
            return {
                "overall_status": status,
                "allow_new_trades": True,
                "allow_monitoring": True,
                "allow_exits": True,
                "action": "ALLOW_WITH_WARNINGS",
                "reason": (
                    f"{len(active_incidents)} active incident(s) under observation"
                    if active_incidents
                    else "Warnings present"
                ),
            }

        return {
            "overall_status": status,
            "allow_new_trades": True,
            "allow_monitoring": True,
            "allow_exits": True,
            "action": "NORMAL_OPERATION",
            "reason": "No active incidents",
        }
