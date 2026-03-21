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

ESCALATION_WINDOW = timedelta(hours=1)
LOW_TO_MEDIUM_COUNT = 3
MEDIUM_TO_HIGH_COUNT = 3
RECENT_RESOLVED_WINDOW = timedelta(hours=1)
CRITICAL_TO_DEGRADED_COOLDOWN = timedelta(minutes=5)
DEGRADED_TO_HEALTHY_COOLDOWN = timedelta(minutes=10)
ANTI_FLAP_WINDOW = timedelta(minutes=15)
ANTI_FLAP_LOCK = timedelta(minutes=10)
ANTI_FLAP_TRANSITIONS = 4


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
            "observed_status": HEALTHY,
            "active_incidents": [],
            "resolved_incidents": [],
            "last_updated": utc_now().isoformat(),
            "affected_components": [],
            "cooldown_start_time": None,
            "cooldown_remaining": 0,
            "cooldown_target": None,
            "stable_since": None,
            "recovery_state": "NORMAL",
            "anti_flapping_until": None,
            "transition_history": [],
        }

    def load_state(self) -> dict[str, Any]:
        state = safe_read_json(self.health_file) or {}
        return {**self.default_state(), **state}

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

    def _incident_records(
        self,
        *,
        incident_type: str | None = None,
        source: str | None = None,
        severity: str | None = None,
        status: str | None = None,
        affected_trade: str | None = None,
        metadata_match: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for incident in safe_read_jsonl(self.incidents_log):
            if incident_type and incident.get("type") != incident_type:
                continue
            if source and incident.get("source") != source:
                continue
            if severity and incident.get("severity") != severity:
                continue
            if status and incident.get("status") != status:
                continue
            if affected_trade and incident.get("affected_trade") != affected_trade:
                continue
            if metadata_match:
                metadata = incident.get("metadata") or {}
                if any(metadata.get(key) != value for key, value in metadata_match.items()):
                    continue
            records.append(incident)
        return records

    def _recent_incidents(
        self,
        *,
        window: timedelta,
        incident_type: str | None = None,
        source: str | None = None,
        severity: str | None = None,
    ) -> list[dict[str, Any]]:
        cutoff = utc_now() - window
        recent: list[dict[str, Any]] = []
        for incident in self._incident_records(
            incident_type=incident_type,
            source=source,
            severity=severity,
            status="ACTIVE",
        ):
            incident_time = self._parse_timestamp(incident.get("timestamp"))
            if incident_time is not None and incident_time >= cutoff:
                recent.append(incident)
        return recent

    def _latest_incident_snapshots(self) -> dict[str, dict[str, Any]]:
        snapshots: dict[str, dict[str, Any]] = {}
        for incident in safe_read_jsonl(self.incidents_log):
            incident_id = incident.get("incident_id")
            if not incident_id:
                continue
            snapshots[incident_id] = incident
        return snapshots

    def _active_and_resolved_incidents(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        now = utc_now()
        active_incidents: list[dict[str, Any]] = []
        resolved_incidents: list[dict[str, Any]] = []
        for incident in self._latest_incident_snapshots().values():
            if incident.get("status") == "RESOLVED":
                resolved_time = self._parse_timestamp(incident.get("resolution_timestamp"))
                if resolved_time and resolved_time >= now - RECENT_RESOLVED_WINDOW:
                    resolved_incidents.append(incident)
                continue
            active_incidents.append(incident)
        active_incidents.sort(key=lambda item: item.get("timestamp", ""))
        resolved_incidents.sort(key=lambda item: item.get("resolution_timestamp", ""))
        return active_incidents[-25:], resolved_incidents[-10:]

    def _base_status(self, active_incidents: list[dict[str, Any]]) -> str:
        if any(incident.get("severity") == "CRITICAL" for incident in active_incidents):
            return CRITICAL
        if active_incidents:
            return DEGRADED
        return HEALTHY

    def _append_transition(self, history: list[dict[str, Any]], status: str, timestamp: str) -> list[dict[str, Any]]:
        updated = [entry for entry in history if self._parse_timestamp(entry.get("timestamp")) and self._parse_timestamp(entry.get("timestamp")) >= utc_now() - ANTI_FLAP_WINDOW]
        if not updated or updated[-1].get("status") != status:
            updated.append({"status": status, "timestamp": timestamp})
        return updated[-10:]

    def _cooldown_remaining_seconds(self, start_time: str | None, cooldown: timedelta, now: datetime) -> int:
        started_at = self._parse_timestamp(start_time)
        if started_at is None:
            return int(cooldown.total_seconds())
        remaining = cooldown - (now - started_at)
        return max(0, int(remaining.total_seconds()))

    def _apply_recovery_controls(
        self,
        previous_state: dict[str, Any],
        observed_status: str,
        active_incidents: list[dict[str, Any]],
    ) -> dict[str, Any]:
        now = utc_now()
        now_iso = now.isoformat()
        previous_status = previous_state.get("overall_status", HEALTHY)
        stable_since = previous_state.get("stable_since")
        if previous_state.get("observed_status") != observed_status:
            stable_since = now_iso

        transition_history = previous_state.get("transition_history", [])
        anti_flapping_until = previous_state.get("anti_flapping_until")
        anti_flap_active = False

        recent_transitions = [
            entry
            for entry in transition_history
            if self._parse_timestamp(entry.get("timestamp")) and self._parse_timestamp(entry.get("timestamp")) >= now - ANTI_FLAP_WINDOW
        ]
        if (
            observed_status != previous_state.get("observed_status")
            and len(recent_transitions) >= ANTI_FLAP_TRANSITIONS - 1
        ):
            anti_flapping_until = (now + ANTI_FLAP_LOCK).isoformat()

        anti_flap_until_dt = self._parse_timestamp(anti_flapping_until)
        if anti_flap_until_dt and anti_flap_until_dt > now and observed_status != CRITICAL:
            anti_flap_active = True

        effective_status = observed_status
        cooldown_target = None
        cooldown_start_time = None
        cooldown_remaining = 0
        recovery_state = "NORMAL"

        if observed_status == CRITICAL:
            recovery_state = "INCIDENT_ACTIVE"
        elif anti_flap_active:
            effective_status = DEGRADED
            recovery_state = "ANTI_FLAP_LOCK"
            cooldown_remaining = max(0, int((anti_flap_until_dt - now).total_seconds()))
        elif previous_status == CRITICAL and observed_status in {DEGRADED, HEALTHY}:
            cooldown_target = DEGRADED
            cooldown_start_time = stable_since
            cooldown_remaining = self._cooldown_remaining_seconds(
                cooldown_start_time,
                CRITICAL_TO_DEGRADED_COOLDOWN,
                now,
            )
            if cooldown_remaining > 0:
                effective_status = CRITICAL
                recovery_state = "CRITICAL_COOLDOWN"
            else:
                effective_status = DEGRADED
                recovery_state = "RECOVERING_TO_DEGRADED"
                stable_since = stable_since or now_iso
        elif previous_status == DEGRADED and observed_status == HEALTHY:
            cooldown_target = HEALTHY
            cooldown_start_time = stable_since
            cooldown_remaining = self._cooldown_remaining_seconds(
                cooldown_start_time,
                DEGRADED_TO_HEALTHY_COOLDOWN,
                now,
            )
            if cooldown_remaining > 0:
                effective_status = DEGRADED
                recovery_state = "DEGRADED_COOLDOWN"
            else:
                effective_status = HEALTHY
        elif not active_incidents and observed_status == HEALTHY:
            recovery_state = "NORMAL"

        transition_history = self._append_transition(
            transition_history,
            effective_status,
            now_iso,
        )

        return {
            "overall_status": effective_status,
            "observed_status": observed_status,
            "stable_since": stable_since,
            "cooldown_target": cooldown_target,
            "cooldown_start_time": cooldown_start_time,
            "cooldown_remaining": cooldown_remaining,
            "recovery_state": recovery_state,
            "anti_flapping_until": anti_flapping_until,
            "transition_history": transition_history,
        }

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
        previous_state = self.load_state()
        active_incidents, resolved_incidents = self._active_and_resolved_incidents()
        affected_components = sorted(
            {
                component
                for incident in active_incidents
                for component in incident.get("affected_components", [])
                if component
            }
        )
        observed_status = self._base_status(active_incidents)
        recovery = self._apply_recovery_controls(previous_state, observed_status, active_incidents)

        state = {
            "overall_status": recovery["overall_status"],
            "observed_status": recovery["observed_status"],
            "active_incidents": active_incidents,
            "resolved_incidents": resolved_incidents,
            "last_updated": utc_now().isoformat(),
            "affected_components": affected_components,
            "cooldown_start_time": recovery["cooldown_start_time"],
            "cooldown_remaining": recovery["cooldown_remaining"],
            "cooldown_target": recovery["cooldown_target"],
            "stable_since": recovery["stable_since"],
            "recovery_state": recovery["recovery_state"],
            "anti_flapping_until": recovery["anti_flapping_until"],
            "transition_history": recovery["transition_history"],
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
        incident_id = f"{source}:{incident_type}:{timestamp}"
        incident = {
            "incident_id": incident_id,
            "type": incident_type,
            "severity": escalated_severity,
            "timestamp": timestamp,
            "status": "ACTIVE",
            "resolution_timestamp": None,
            "resolution_reason": None,
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

    def resolve_incident(
        self,
        *,
        incident_type: str,
        source: str,
        resolution_reason: str,
        affected_trade: str | None = None,
        metadata_match: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        latest_records = self._latest_incident_snapshots()
        resolved = 0
        resolution_timestamp = utc_now().isoformat()
        for incident in latest_records.values():
            if incident.get("status") != "ACTIVE":
                continue
            if incident.get("type") != incident_type or incident.get("source") != source:
                continue
            if affected_trade and incident.get("affected_trade") != affected_trade:
                continue
            if metadata_match:
                metadata = incident.get("metadata") or {}
                if any(metadata.get(key) != value for key, value in metadata_match.items()):
                    continue
            updated_incident = {
                **incident,
                "status": "RESOLVED",
                "resolution_timestamp": resolution_timestamp,
                "resolution_reason": resolution_reason,
            }
            self._append_incident(updated_incident)
            resolved += 1

        state = self.refresh_state()
        return {"resolved_count": resolved, "state": state}

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
                    else f"Critical recovery hold: {state.get('recovery_state', 'INCIDENT_ACTIVE')}"
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
                    f"Recovery state {state.get('recovery_state')}; "
                    f"{len(active_incidents)} active incident(s) under observation"
                    if active_incidents or state.get("recovery_state") != "NORMAL"
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
