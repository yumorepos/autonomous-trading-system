from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from config.runtime import LOGS_DIR, WORKSPACE_ROOT
from utils.json_utils import safe_read_json, safe_read_jsonl, write_json_atomic

SYSTEM_HEALTH_FILE = WORKSPACE_ROOT / "system_health.json"
SYSTEM_INCIDENTS_LOG = LOGS_DIR / "system-incidents.jsonl"
OPERATOR_CONTROL_FILE = WORKSPACE_ROOT / "operator_control.json"
SYSTEM_STATUS_FILE = WORKSPACE_ROOT / "system_status.json"
OPERATOR_ACTIONS_LOG = LOGS_DIR / "operator-actions.jsonl"
OPERATOR_AUDIT_STATE_FILE = LOGS_DIR / "operator-control-audit.json"

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

OPERATOR_CONTROL_DEFAULTS = {
    "manual_mode": "OFF",
    "trading_override": "ALLOW",
    "recovery_override": "AUTO",
    "notes": "",
    "updated_at": None,
}
MANUAL_MODE_VALUES = {"ON", "OFF"}
TRADING_OVERRIDE_VALUES = {"ALLOW", "RESTRICT", "HALT_NEW_TRADES"}
RECOVERY_OVERRIDE_VALUES = {"AUTO", "HOLD_DEGRADED", "HOLD_CRITICAL"}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SystemHealthManager:
    """Central health-state manager for incidents, escalation, recovery, and operator controls."""

    def __init__(self):
        self.health_file = SYSTEM_HEALTH_FILE
        self.incidents_log = SYSTEM_INCIDENTS_LOG
        self.operator_control_file = OPERATOR_CONTROL_FILE
        self.system_status_file = SYSTEM_STATUS_FILE
        self.operator_actions_log = OPERATOR_ACTIONS_LOG
        self.operator_audit_state_file = OPERATOR_AUDIT_STATE_FILE
        if not self.health_file.exists():
            self.save_state(self.default_state())
        self._ensure_operator_control_file()

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

    def default_operator_control(self) -> dict[str, Any]:
        return dict(OPERATOR_CONTROL_DEFAULTS)

    def _ensure_operator_control_file(self) -> None:
        if not self.operator_control_file.exists():
            write_json_atomic(self.operator_control_file, self.default_operator_control())
        if not self.operator_audit_state_file.exists():
            control = safe_read_json(self.operator_control_file) or self.default_operator_control()
            write_json_atomic(
                self.operator_audit_state_file,
                {
                    "last_seen_updated_at": control.get("updated_at"),
                    "last_control": {
                        key: control.get(key, default)
                        for key, default in OPERATOR_CONTROL_DEFAULTS.items()
                    },
                },
            )

    def load_state(self) -> dict[str, Any]:
        state = safe_read_json(self.health_file) or {}
        return {**self.default_state(), **state}

    def save_state(self, state: dict[str, Any]) -> None:
        write_json_atomic(self.health_file, state)

    def _append_jsonl(self, path: Path, record: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as handle:
            handle.write(json.dumps(record) + "\n")

    def _append_incident(self, incident: dict[str, Any]) -> None:
        self._append_jsonl(self.incidents_log, incident)

    def _append_operator_action(self, action: dict[str, Any]) -> None:
        self._append_jsonl(self.operator_actions_log, action)

    def _parse_timestamp(self, timestamp: str | None) -> datetime | None:
        if not timestamp:
            return None
        try:
            return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            return None

    def load_operator_control(self) -> dict[str, Any]:
        raw_control = safe_read_json(self.operator_control_file) or {}
        control = {**self.default_operator_control(), **raw_control}
        validation_errors: list[str] = []

        manual_mode = str(control.get("manual_mode", "OFF")).upper()
        if manual_mode not in MANUAL_MODE_VALUES:
            validation_errors.append(
                f"manual_mode={control.get('manual_mode')} invalid; expected one of {sorted(MANUAL_MODE_VALUES)}"
            )
            manual_mode = OPERATOR_CONTROL_DEFAULTS["manual_mode"]

        trading_override = str(control.get("trading_override", "ALLOW")).upper()
        if trading_override not in TRADING_OVERRIDE_VALUES:
            validation_errors.append(
                f"trading_override={control.get('trading_override')} invalid; expected one of {sorted(TRADING_OVERRIDE_VALUES)}"
            )
            trading_override = OPERATOR_CONTROL_DEFAULTS["trading_override"]

        recovery_override = str(control.get("recovery_override", "AUTO")).upper()
        if recovery_override not in RECOVERY_OVERRIDE_VALUES:
            validation_errors.append(
                f"recovery_override={control.get('recovery_override')} invalid; expected one of {sorted(RECOVERY_OVERRIDE_VALUES)}"
            )
            recovery_override = OPERATOR_CONTROL_DEFAULTS["recovery_override"]

        normalized = {
            **control,
            "manual_mode": manual_mode,
            "trading_override": trading_override,
            "recovery_override": recovery_override,
            "notes": str(control.get("notes") or ""),
            "updated_at": control.get("updated_at"),
            "validation_errors": validation_errors,
            "is_valid": len(validation_errors) == 0,
        }
        self._sync_operator_action_log(normalized)
        return normalized

    def _sync_operator_action_log(self, operator_control: dict[str, Any]) -> None:
        audit_state = safe_read_json(self.operator_audit_state_file) or {}
        previous_control = audit_state.get("last_control") or {
            key: OPERATOR_CONTROL_DEFAULTS[key]
            for key in OPERATOR_CONTROL_DEFAULTS
        }
        last_seen_updated_at = audit_state.get("last_seen_updated_at")
        current_updated_at = operator_control.get("updated_at")

        comparable_control = {
            key: operator_control.get(key, default)
            for key, default in OPERATOR_CONTROL_DEFAULTS.items()
        }

        if current_updated_at == last_seen_updated_at and comparable_control == previous_control:
            return

        if audit_state:
            reason = operator_control.get("notes") or "No operator reason provided"
            timestamp = current_updated_at or utc_now().isoformat()
            for field in ("manual_mode", "trading_override", "recovery_override", "notes"):
                old_value = previous_control.get(field)
                new_value = comparable_control.get(field)
                if old_value == new_value:
                    continue
                self._append_operator_action(
                    {
                        "timestamp": timestamp,
                        "field": field,
                        "previous_value": old_value,
                        "new_value": new_value,
                        "reason": reason,
                    }
                )

        write_json_atomic(
            self.operator_audit_state_file,
            {
                "last_seen_updated_at": current_updated_at,
                "last_control": comparable_control,
            },
        )

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
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        cutoff = utc_now() - window
        recent: list[dict[str, Any]] = []
        for incident in self._incident_records(
            incident_type=incident_type,
            source=source,
            severity=severity,
            status=status,
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
        updated = [
            entry
            for entry in history
            if self._parse_timestamp(entry.get("timestamp"))
            and self._parse_timestamp(entry.get("timestamp")) >= utc_now() - ANTI_FLAP_WINDOW
        ]
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
            if self._parse_timestamp(entry.get("timestamp"))
            and self._parse_timestamp(entry.get("timestamp")) >= now - ANTI_FLAP_WINDOW
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
                status="ACTIVE",
            )
            if len(low_incidents) >= LOW_TO_MEDIUM_COUNT - 1:
                return "MEDIUM", "Repeated LOW incidents escalated to MEDIUM"

        if normalized == "MEDIUM":
            medium_incidents = self._recent_incidents(
                window=ESCALATION_WINDOW,
                incident_type=incident_type,
                source=source,
                severity="MEDIUM",
                status="ACTIVE",
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

    def _apply_operator_overrides(self, state: dict[str, Any], base_response: dict[str, Any]) -> dict[str, Any]:
        operator_control = self.load_operator_control()
        effective_state = dict(state)
        response = dict(base_response)
        override_effects: list[str] = []
        safety_lock_reason: str | None = None

        if operator_control["manual_mode"] == "ON":
            if operator_control["recovery_override"] == "HOLD_CRITICAL" and state["overall_status"] != CRITICAL:
                effective_state["overall_status"] = CRITICAL
                effective_state["recovery_state"] = "OPERATOR_HOLD_CRITICAL"
                effective_state["cooldown_target"] = effective_state.get("cooldown_target") or DEGRADED
                override_effects.append("operator_hold_critical")
            elif operator_control["recovery_override"] == "HOLD_DEGRADED" and state["overall_status"] == HEALTHY:
                effective_state["overall_status"] = DEGRADED
                effective_state["recovery_state"] = "OPERATOR_HOLD_DEGRADED"
                effective_state["cooldown_target"] = effective_state.get("cooldown_target") or HEALTHY
                override_effects.append("operator_hold_degraded")

            if operator_control["trading_override"] == "HALT_NEW_TRADES" and effective_state["overall_status"] != CRITICAL:
                override_effects.append("operator_halt_new_trades")
            elif operator_control["trading_override"] == "RESTRICT" and response.get("action") == "NORMAL_OPERATION":
                response["action"] = "ALLOW_WITH_WARNINGS"
                response["reason"] = "Operator manual mode enabled with RESTRICT override"
                override_effects.append("operator_restrict")

        if effective_state["overall_status"] == CRITICAL:
            safety_lock_reason = (
                base_response.get("reason")
                if state["overall_status"] == CRITICAL
                else "Operator hold prevents automatic recovery while preserving CRITICAL protections"
            )
            response.update(
                {
                    "overall_status": CRITICAL,
                    "allow_new_trades": False,
                    "allow_monitoring": True,
                    "allow_exits": True,
                    "action": "HALT_NEW_TRADES",
                    "reason": safety_lock_reason,
                }
            )
        elif response.get("action") != "HALT_NEW_TRADES" and operator_control["manual_mode"] == "ON":
            if operator_control["trading_override"] == "HALT_NEW_TRADES":
                response.update(
                    {
                        "overall_status": effective_state["overall_status"],
                        "allow_new_trades": False,
                        "allow_monitoring": True,
                        "allow_exits": True,
                        "action": "HALT_NEW_TRADES",
                        "reason": "Operator manual halt on new trades",
                    }
                )
            elif effective_state["overall_status"] == DEGRADED and response.get("action") == "NORMAL_OPERATION":
                response.update(
                    {
                        "overall_status": DEGRADED,
                        "allow_new_trades": True,
                        "allow_monitoring": True,
                        "allow_exits": True,
                        "action": "ALLOW_WITH_WARNINGS",
                        "reason": "Operator hold keeps system degraded for manual inspection",
                    }
                )
            else:
                response["overall_status"] = effective_state["overall_status"]

        response["operator_control"] = {
            "manual_mode": operator_control["manual_mode"],
            "trading_override": operator_control["trading_override"],
            "recovery_override": operator_control["recovery_override"],
            "notes": operator_control.get("notes", ""),
            "updated_at": operator_control.get("updated_at"),
            "validation_errors": operator_control.get("validation_errors", []),
            "override_effects": override_effects,
        }
        response["recovery_state"] = effective_state.get("recovery_state")
        response["cooldown_remaining"] = effective_state.get("cooldown_remaining", 0)
        return {"state": effective_state, "response": response, "operator_control": operator_control}

    def _classify_alert_level(self, state: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
        active_incidents = state.get("active_incidents", [])
        resolved_incidents = state.get("resolved_incidents", [])
        reasons: list[str] = []
        level = "INFO"

        repeated_integrity_or_execution_failures = len(
            [
                incident
                for incident in self._recent_incidents(window=ESCALATION_WINDOW, status="ACTIVE")
                if incident.get("source") in {"data-integrity-layer", "execution-safety-layer"}
            ]
        ) >= 3

        if response.get("action") == "HALT_NEW_TRADES":
            level = "CRITICAL"
            reasons.append("HALT_NEW_TRADES active")
        if any(incident.get("severity") == "CRITICAL" for incident in active_incidents):
            level = "CRITICAL"
            reasons.append("Unresolved CRITICAL incident present")
        if repeated_integrity_or_execution_failures:
            level = "CRITICAL"
            reasons.append("Repeated execution/integrity failures detected")

        if level != "CRITICAL":
            repeated_low_or_medium = len(
                [
                    incident
                    for incident in self._recent_incidents(window=ESCALATION_WINDOW, status="ACTIVE")
                    if incident.get("severity") in {"LOW", "MEDIUM"}
                ]
            ) >= 3
            if state.get("overall_status") == DEGRADED:
                level = "WARNING"
                reasons.append("System operating in DEGRADED state")
            if state.get("cooldown_remaining", 0) > 0:
                level = "WARNING"
                reasons.append("Recovery cooldown active")
            if repeated_low_or_medium:
                level = "WARNING"
                reasons.append("Repeated LOW/MEDIUM incidents detected")
            if active_incidents and not reasons:
                level = "WARNING"
                reasons.append("Active incidents under observation")

        if level == "INFO" and resolved_incidents:
            low_resolved = [incident for incident in resolved_incidents if incident.get("severity") == "LOW"]
            if low_resolved:
                reasons.append("Resolved LOW incidents logged")
            else:
                reasons.append("Normal recovery/monitoring state")
        elif level == "INFO":
            reasons.append("Normal recovery/monitoring state")

        return {"level": level, "reasons": reasons}

    def _build_system_status(self, state: dict[str, Any], response: dict[str, Any], alert_policy: dict[str, Any]) -> dict[str, Any]:
        operator_control = response.get("operator_control", {})
        return {
            "timestamp": utc_now().isoformat(),
            "current_health_status": state.get("overall_status"),
            "observed_health_status": state.get("observed_status"),
            "recovery_state": state.get("recovery_state"),
            "cooldown_remaining": state.get("cooldown_remaining", 0),
            "cooldown_target": state.get("cooldown_target"),
            "active_incidents": state.get("active_incidents", []),
            "recently_resolved_incidents": state.get("resolved_incidents", []),
            "operator_overrides": {
                "manual_mode": operator_control.get("manual_mode", "OFF"),
                "trading_override": operator_control.get("trading_override", "ALLOW"),
                "recovery_override": operator_control.get("recovery_override", "AUTO"),
                "notes": operator_control.get("notes", ""),
                "updated_at": operator_control.get("updated_at"),
                "validation_errors": operator_control.get("validation_errors", []),
                "override_effects": operator_control.get("override_effects", []),
            },
            "current_action": response.get("action"),
            "alert": alert_policy,
            "trading_permissions": {
                "allow_new_trades": response.get("allow_new_trades", True),
                "allow_monitoring": response.get("allow_monitoring", True),
                "allow_exits": response.get("allow_exits", True),
            },
            "reason": response.get("reason"),
        }

    def write_system_status(self) -> dict[str, Any]:
        state = self.refresh_state()
        base_response = self._automatic_trading_response(state)
        governed = self._apply_operator_overrides(state, base_response)
        alert_policy = self._classify_alert_level(governed["state"], governed["response"])
        governed["response"]["alert_level"] = alert_policy["level"]
        governed["response"]["alert_reasons"] = alert_policy["reasons"]
        system_status = self._build_system_status(governed["state"], governed["response"], alert_policy)
        write_json_atomic(self.system_status_file, system_status)
        return system_status

    def _automatic_trading_response(self, state: dict[str, Any]) -> dict[str, Any]:
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
        self.write_system_status()
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
        self.write_system_status()
        return {"resolved_count": resolved, "state": state}

    def trading_response(self) -> dict[str, Any]:
        state = self.refresh_state()
        base_response = self._automatic_trading_response(state)
        governed = self._apply_operator_overrides(state, base_response)
        alert_policy = self._classify_alert_level(governed["state"], governed["response"])
        governed["response"]["alert_level"] = alert_policy["level"]
        governed["response"]["alert_reasons"] = alert_policy["reasons"]
        write_json_atomic(
            self.system_status_file,
            self._build_system_status(governed["state"], governed["response"], alert_policy),
        )
        return governed["response"]
