#!/usr/bin/env python3
"""Execute package templates/actions against deterministic HA boundary fixtures.

This is not a Home Assistant configuration validator. It uses the already
available PyYAML/Jinja2 libraries and replaces only HA services, state, and time.
Queued variables follow core 2026.9.1 helpers/script.py; Kodi event fixtures
follow components/kodi/media_player.py at that same tag.
"""

import ast
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import shlex
import sys
from types import SimpleNamespace

import jinja2
import yaml


SONY = "media_player.sony_xr_65a90j"
KODI = "media_player.kodi_theater"
IDLE = "input_boolean.ugoos_theater_input_idle"
SENT = "input_boolean.ugoos_theater_idle_poweroff_sent"
KEEP = "input_boolean.ugoos_theater_keep_kodi_running"
HOST = "input_boolean.ugoos_theater_host_reachable"
PROBE_TIME = "input_datetime.ugoos_theater_idle_probe_updated"
RECONCILE_TIME = "input_datetime.ugoos_theater_last_reconciliation"
ACTUAL = "input_text.ugoos_theater_kodi_lifecycle_state"
RECONCILE = "ugoos_theater_reconcile_kodi"
POWER_OFF = "ugoos_theater_power_off_idle_sony"
EPOCH = "input_datetime.ugoos_theater_observation_started"
OBSERVING = "input_boolean.ugoos_theater_observation_ready"
LAST_ERROR = "input_text.ugoos_theater_last_lifecycle_error"


class Stopped(Exception):
    pass


class ServiceFailure(Exception):
    pass


class States:
    def __init__(self, fixture, domain=None):
        self.fixture = fixture
        self.domain = domain

    def __call__(self, entity):
        if entity == "sensor.ugoos_theater_desired_kodi_state":
            sensor = self.fixture.package["template"][0]["sensor"][0]
            return self.fixture.render(sensor["state"], {})
        return self.fixture.entities.get(entity, SimpleNamespace(state="unknown")).state

    def __getattr__(self, name):
        if self.domain is None:
            return States(self.fixture, name)
        return self.fixture.entities.get(f"{self.domain}.{name}")


class Package:
    def __init__(self, path):
        self.package = yaml.safe_load(Path(path).read_text())
        self.now = datetime(2026, 9, 11, 12, tzinfo=timezone.utc)
        self.entities = {}
        self.notifications = {}
        self.calls = []
        self.responses = {}
        self.action_hooks = {}
        self.service = "running"
        self.fail_actions = set()
        self.wait_hook = None
        self.queued = deque()
        self.timers = []
        self.auto_events = False
        self.env = jinja2.Environment(undefined=jinja2.StrictUndefined)
        self.env.filters["regex_replace"] = lambda value, find="", replace="": re.sub(
            find, replace, str(value)
        )
        self.env.filters["bool"] = lambda value: str(value).lower() in ("true", "on", "1")
        self.env.globals.update(
            states=States(self),
            is_state=lambda entity, value: States(self)(entity) == value,
            as_timestamp=self.timestamp,
            now=lambda: self.now,
        )
        for domain in ("input_boolean", "input_number", "input_datetime", "input_text"):
            for name, config in self.package.get(domain, {}).items():
                value = config.get("initial", "off" if domain == "input_boolean" else "unknown")
                if isinstance(value, bool):
                    value = "on" if value else "off"
                self.set_state(f"{domain}.{name}", str(value), age=3600)
        self.set_state(SONY, "on", age=3600)
        self.set_state(KODI, "idle", age=3600)
        self.set_state(PROBE_TIME, self.now.isoformat())

    @staticmethod
    def timestamp(value, default=None):
        try:
            if isinstance(value, datetime):
                return value.timestamp()
            if isinstance(value, (int, float)):
                return value
            return datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp()
        except (TypeError, ValueError):
            if default is not None:
                return default
            raise

    def set_state(self, entity, value, age=0):
        old = self.entities.get(entity)
        changed = self.now - timedelta(seconds=age)
        if old and old.state == str(value) and not age:
            changed = old.last_changed
        state = SimpleNamespace(
            entity_id=entity, state=str(value), last_changed=changed,
            last_updated=self.now, attributes={},
        )
        self.entities[entity] = state
        return old, state

    def update(self, entity, value):
        if self.auto_events:
            return self.state_event(entity, value)
        return self.set_state(entity, value)

    def state_event(self, entity, value):
        old, new = self.set_state(entity, value)
        if old is not None and old.state == new.state:
            return
        for definition in self.package["automation"]:
            for trigger in definition["triggers"]:
                targets = trigger.get("entity_id", [])
                if isinstance(targets, str):
                    targets = [targets]
                if trigger.get("trigger") != "state" or entity not in targets:
                    continue
                matches = True
                for key, actual in (
                    ("from", old.state if old else None), ("to", new.state),
                    ("not_from", old.state if old else None), ("not_to", new.state),
                ):
                    if key not in trigger:
                        continue
                    expected = trigger[key]
                    expected = expected if isinstance(expected, list) else [expected]
                    result = actual in expected
                    matches = matches and (not result if key.startswith("not_") else result)
                if not matches:
                    continue
                event = {"platform": "state", "entity_id": entity, "from_state": old,
                         "to_state": new, "id": trigger.get("id", "0")}
                if "for" in trigger:
                    self.timers.append((
                        self.now + timedelta(seconds=self.seconds(trigger["for"])),
                        entity, new.last_changed, definition["id"], event,
                    ))
                else:
                    self.automation(definition["id"], event)
                break

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)
        due = [timer for timer in self.timers if timer[0] <= self.now]
        self.timers = [timer for timer in self.timers if timer[0] > self.now]
        for _, entity, changed, automation, event in due:
            if self.entities[entity].last_changed == changed:
                self.automation(automation, event)

    def drain(self):
        count = 0
        while self.queued:
            count += 1
            assert count < 12, "package created an unbounded reconciliation loop"
            self.run_next()

    def render(self, value, variables):
        if isinstance(value, dict):
            return {key: self.render(item, variables) for key, item in value.items()}
        if isinstance(value, list):
            return [self.render(item, variables) for item in value]
        if not isinstance(value, str) or not ("{{" in value or "{%" in value):
            return value
        result = self.env.from_string(value).render(**variables).strip()
        try:
            return ast.literal_eval(result)
        except (ValueError, SyntaxError):
            return result

    def variables(self, definitions, scope):
        for name, template in definitions.items():
            scope[name] = self.render(template, scope)

    def condition(self, condition, scope):
        if isinstance(condition, list):
            return all(self.condition(item, scope) for item in condition)
        if isinstance(condition, str):
            return self.render(condition, scope) is True
        kind = condition["condition"]
        if kind == "template":
            try:
                return self.render(condition["value_template"], scope) is True
            except jinja2.UndefinedError:
                return False
        if kind == "state":
            return States(self)(condition["entity_id"]) == str(condition["state"])
        if kind == "or":
            return any(self.condition(item, scope) for item in condition["conditions"])
        if kind == "and":
            return self.condition(condition["conditions"], scope)
        raise AssertionError(f"unsupported fixture condition: {kind}")

    @staticmethod
    def seconds(value):
        if isinstance(value, (int, float)):
            return value
        hours, minutes, seconds = map(int, value.split(":"))
        return hours * 3600 + minutes * 60 + seconds

    def sequence(self, actions, scope):
        for step in actions:
            if "variables" in step:
                self.variables(step["variables"], scope)
            elif "condition" in step:
                if not self.condition(step, scope):
                    raise Stopped()
            elif "choose" in step:
                chosen = next(
                    (choice["sequence"] for choice in step["choose"]
                     if self.condition(choice["conditions"], scope)),
                    step.get("default", []),
                )
                self.sequence(chosen, scope)
            elif "if" in step:
                self.sequence(
                    step["then"] if self.condition(step["if"], scope)
                    else step.get("else", []), scope,
                )
            elif "wait_template" in step:
                complete = self.render(step["wait_template"], scope) is True
                if not complete:
                    self.now += timedelta(seconds=self.seconds(step["timeout"]))
                    if self.wait_hook:
                        self.wait_hook(self, step)
                    complete = self.render(step["wait_template"], scope) is True
                scope["wait"] = {"completed": complete}
                if not complete and not step.get("continue_on_timeout", True):
                    raise Stopped()
            elif "delay" in step:
                self.now += timedelta(seconds=self.seconds(step["delay"]))
            elif "stop" in step:
                raise Stopped()
            elif "action" in step:
                try:
                    self.action(step, scope)
                except ServiceFailure:
                    if not step.get("continue_on_error", False):
                        raise
            else:
                raise AssertionError(f"unsupported package step: {step}")

    def action(self, step, scope):
        name = self.render(step["action"], scope)
        data = self.render(step.get("data", {}), scope)
        target = self.render(step.get("target", {}), scope)
        entities = target.get("entity_id", [])
        if isinstance(entities, str):
            entities = [entities]
        if name.split(".", 1)[0] in ("input_boolean", "input_text", "input_datetime"):
            for entity in entities:
                domain, key = entity.split(".", 1)
                assert key in self.package[domain], f"action targets undeclared helper {entity}"
        self.calls.append((name, target, data))
        hook = self.action_hooks.get(name)
        if hook:
            hook(self)
        if name in self.fail_actions:
            raise ServiceFailure(name)
        if name.startswith("shell_command."):
            command = name.rsplit("_", 1)[1]
            if command in self.responses and self.responses[command]:
                response = self.responses[command].popleft()
            else:
                if command == "start":
                    self.service = "running"
                elif command == "stop":
                    self.service = "stopped"
                response = {"returncode": 0, "stdout": self.service + "\n", "stderr": ""}
            scope[step["response_variable"]] = response
        elif name in ("input_boolean.turn_on", "input_boolean.turn_off"):
            for entity in entities:
                self.update(entity, "on" if name.endswith("turn_on") else "off")
        elif name == "input_text.set_value":
            for entity in entities:
                self.update(entity, data["value"])
        elif name == "input_datetime.set_datetime":
            for entity in entities:
                value = data.get("datetime")
                if value is None:
                    value = datetime.fromtimestamp(float(data["timestamp"]), timezone.utc).isoformat()
                self.update(entity, value)
        elif name == "persistent_notification.create":
            self.notifications[data["notification_id"]] = data["message"]
        elif name == "persistent_notification.dismiss":
            self.notifications.pop(data["notification_id"], None)
        elif name == "script.turn_on":
            for entity in entities:
                self.enqueue(entity.split(".", 1)[1], data.get("variables", {}))
        elif name.startswith("script."):
            self.run_script(name.split(".", 1)[1], data)
        elif name in ("media_player.turn_off", "kodi.call_method"):
            pass
        else:
            raise AssertionError(f"unsupported package service: {name}")

    def enqueue(self, name, data=None):
        scope = dict(data or {})
        self.variables(self.package["script"][name].get("variables", {}), scope)
        self.queued.append((name, scope))

    def run_next(self):
        name, scope = self.queued.popleft()
        try:
            self.sequence(self.package["script"][name]["sequence"], scope)
        except Stopped:
            pass

    def run_script(self, name, data=None):
        scope = dict(data or {})
        self.variables(self.package["script"][name].get("variables", {}), scope)
        try:
            self.sequence(self.package["script"][name]["sequence"], scope)
        except Stopped:
            pass

    def automation(self, name, trigger=None):
        definition = next(item for item in self.package["automation"] if item["id"] == name)
        scope = {"trigger": trigger or {}}
        self.variables(definition.get("variables", {}), scope)
        if self.condition(definition.get("conditions", []), scope):
            try:
                self.sequence(definition["actions"], scope)
            except Stopped:
                pass

    def event(self, event_type, data=None):
        for definition in self.package["automation"]:
            for trigger in definition["triggers"]:
                if (trigger.get("trigger") == "event" and trigger["event_type"] == event_type
                        and all((data or {}).get(key) == value
                                for key, value in trigger.get("event_data", {}).items())):
                    self.automation(definition["id"], {
                        "platform": "event", "event": {"data": data or {}},
                        "id": trigger.get("id", "0"),
                    })
                    break

    def start(self):
        for definition in self.package["automation"]:
            if any(trigger.get("trigger") == "homeassistant" and trigger["event"] == "start"
                   for trigger in definition["triggers"]):
                self.automation(definition["id"], {"platform": "homeassistant", "event": "start"})

    def commands(self):
        return [name.rsplit("_", 1)[1] for name, _, _ in self.calls
                if name.startswith("shell_command.")]


def kodi_event(value=True, **overrides):
    event = {
        "entity_id": KODI, "result": {"System.IdleTime(1800)": value},
        "result_ok": True,
        "input": {"method": "XBMC.GetInfoBooleans",
                  "params": {"booleans": ["System.IdleTime(1800)"]}},
    }
    event.update(overrides)
    return event


def idle_event_envelope(path):
    p = Package(path)
    p.set_state(IDLE, "off")
    p.event("kodi_call_method_result", kodi_event())
    assert States(p)(IDLE) == "on", "genuine HA input.method/input.params event did not establish idle"
    assert p.timestamp(States(p)(PROBE_TIME)) == p.now.timestamp()
    p.event("kodi_call_method_result", kodi_event(False))
    assert States(p)(IDLE) == "off", "fresh negative input-idle evidence must clear idle"


def idle_event_failed_or_mismatched(path):
    p = Package(path)
    for event in (
        kodi_event(entity_id="media_player.other"),
        kodi_event(input={"method": "Other", "params": {"booleans": ["System.IdleTime(1800)"]}}),
        kodi_event(input={"method": "XBMC.GetInfoBooleans", "params": {"booleans": ["System.IdleTime(300)"]}}),
    ):
        p.set_state(IDLE, "off")
        p.event("kodi_call_method_result", event)
        assert States(p)(IDLE) == "off"
        assert not p.notifications, "unrelated events must not generate alerts"
    for event in (
        kodi_event(result_ok=False), kodi_event(result_ok="true"),
        kodi_event(result_ok=None), kodi_event(value="true"), kodi_event(value=1),
        kodi_event(result={}), kodi_event(result=None),
    ):
        p.set_state(IDLE, "on")
        p.event("kodi_call_method_result", event)
        assert States(p)(IDLE) == "off", "failed/malformed probes must invalidate success-shaped evidence"
        assert "ugoos_theater_kodi_idle_probe" in p.notifications


def idle_probe_request(path):
    for timeout, expected in ((30, "System.IdleTime(1800)"), (5, "System.IdleTime(300)")):
        p = Package(path)
        p.set_state("input_number.ugoos_theater_idle_timeout_minutes", timeout)
        p.automation("ugoos_theater_kodi_idle_probe")
        assert ("kodi.call_method", {"entity_id": KODI}, {
            "method": "XBMC.GetInfoBooleans", "booleans": [expected],
        }) in p.calls
        p.calls.clear()
        p.set_state(KODI, "unavailable")
        p.automation("ugoos_theater_kodi_idle_probe")
        assert not p.calls, "never probe an unavailable Kodi"

def established_pair(p):
    p.set_state(EPOCH, (p.now - timedelta(hours=1)).isoformat())
    p.set_state(OBSERVING, "on")
    p.set_state(HOST, "on")


def queued_reconciliation_current_state(path):
    for entity, value in ((SONY, "on"), (SONY, "unknown"), (KEEP, "on")):
        p = Package(path)
        established_pair(p)
        p.set_state(SONY, "off", age=120)
        p.enqueue(RECONCILE)
        p.set_state(entity, value)
        p.run_next()
        assert "stop" not in p.commands(), f"queued stale stop executed after {entity} became {value}"
        assert p.service == "running"
    p = Package(path)
    established_pair(p)
    p.enqueue(RECONCILE)
    p.now += timedelta(seconds=120)
    p.set_state(SONY, "off", age=120)
    p.run_next()
    assert "stop" in p.commands(), "queued runs must also observe a newly confirmed off interval"


def reconciliation_rechecks_after_status(path):
    p = Package(path)
    established_pair(p)
    p.set_state(SONY, "off", age=120)
    p.action_hooks["shell_command.ugoos_theater_kodi_status"] = lambda p: p.set_state(KEEP, "on")
    p.run_script(RECONCILE)
    assert "stop" not in p.commands(), "a state change during the status round trip must cancel stop"


def stop_eligibility_rechecked(path):
    p = Package(path)
    established_pair(p)
    p.set_state(SONY, "off", age=120)
    p.action_hooks["input_text.set_value"] = lambda p: p.set_state(SONY, "on")
    p.run_script(RECONCILE)
    assert "stop" not in p.commands(), "status bookkeeping must not conceal a canceled off interval"

def recovery_starts_fresh_observation(path):
    for previous_host, previous_service in (("off", "running"), ("on", "stopped"), ("on", "failed")):
        p = Package(path)
        established_pair(p)
        p.auto_events = True
        p.set_state(SONY, "off", age=7200)
        p.set_state(HOST, previous_host)
        p.set_state(ACTUAL, previous_service)
        p.set_state(IDLE, "on")
        p.automation("ugoos_theater_kodi_status_poll")
        assert p.timestamp(States(p)(EPOCH)) == p.now.timestamp(), "recovery reused the pre-outage off epoch"
        assert States(p)(IDLE) == "off", "recovery retained old idle evidence"
        assert p.queued, "status recovery never initiated bounded reconciliation"
        p.drain()
        assert "stop" not in p.commands(), "old Sony-off duration stopped Kodi immediately after recovery"
        p.advance(59)
        p.drain()
        assert "stop" not in p.commands()
        p.advance(1)
        p.drain()
        assert p.service == "stopped", "fresh epoch maturity never reconciled the still-off Sony"
        before = len(p.commands())
        p.advance(120)
        p.drain()
        assert len(p.commands()) == before, "epoch maturity must not retry forever"

def reconciler_first_recovery_starts_fresh_observation(path):
    for previous_host, previous_service in (("on", "stopped"), ("on", "failed"), ("off", "running")):
        p = Package(path)
        established_pair(p)
        p.auto_events = True
        p.set_state(SONY, "off", age=7200)
        p.set_state(HOST, previous_host)
        p.set_state(ACTUAL, previous_service)
        p.set_state(IDLE, "on")
        recovered_at = p.now.timestamp()
        p.run_script(RECONCILE)
        assert p.timestamp(States(p)(EPOCH)) == recovered_at, \
            f"reconciler reused the old recovery epoch at 0s: {p.commands()}"
        assert p.service == "running" and "stop" not in p.commands()
        assert States(p)(IDLE) == "off"
        assert not p.queued, "an executing reconciler must not recursively enqueue itself on recovery"
        p.advance(29)
        p.automation("ugoos_theater_kodi_status_poll")
        p.drain()
        p.advance(30)
        p.run_script(RECONCILE)
        assert p.timestamp(States(p)(EPOCH)) == recovered_at, "ordinary observations restarted the recovery epoch"
        assert "stop" not in p.commands(), "recovered service stopped before sixty fresh seconds"
        p.advance(1)
        p.drain()
        assert p.service == "stopped" and p.commands().count("stop") == 1

def healthy_polls_do_not_retry_failed_command(path, command):
    for failure in (9, 255, "exception"):
        p = Package(path)
        established_pair(p)
        p.auto_events = True
        p.service = "stopped" if command == "start" else "running"
        p.set_state(ACTUAL, p.service)
        if command == "stop":
            p.set_state(SONY, "off", age=7200)
        epoch = States(p)(EPOCH)
        reconciliation = States(p)(RECONCILE_TIME)
        if failure == "exception":
            p.fail_actions.add(f"shell_command.ugoos_theater_kodi_{command}")
        else:
            p.responses[command] = deque(
                {"returncode": failure, "stdout": "", "stderr": f"{command} failed"}
                for _ in range(20)
            )
        p.run_script(RECONCILE)
        attempts = [p.commands().count(command)]
        for _ in range(8):
            p.advance(30)
            p.automation("ugoos_theater_kodi_status_poll")
            p.drain()
            attempts.append(p.commands().count(command))
        assert attempts == [1] * 9, \
            f"healthy status polls retried persistent {command} failure at 0/30/.../240s: {attempts}"
        assert States(p)(EPOCH) == epoch, "a command error fabricated a host recovery epoch"
        assert States(p)(RECONCILE_TIME) == reconciliation, "failed command was certified by a status poll"
        notification = f"ugoos_theater_kodi_lifecycle_{command}"
        assert notification in p.notifications
        p.responses.pop(command, None)
        p.fail_actions.clear()
        p.run_script(RECONCILE)
        assert p.commands().count(command) == 2, "explicit operator retry must remain available"
        assert p.service == ("running" if command == "start" else "stopped")
        assert notification not in p.notifications


def healthy_polls_do_not_retry_start(path):
    healthy_polls_do_not_retry_failed_command(path, "start")


def healthy_polls_do_not_retry_stop(path):
    healthy_polls_do_not_retry_failed_command(path, "stop")


def actual_status_outage_allows_recovery_after_command_failure(path):
    p = Package(path)
    established_pair(p)
    p.auto_events = True
    p.service = "stopped"
    p.set_state(ACTUAL, "stopped")
    p.responses["start"] = deque([{"returncode": 9, "stdout": "", "stderr": "start failed"}])
    p.run_script(RECONCILE)
    assert p.commands().count("start") == 1
    p.responses["status"] = deque([{"returncode": 255, "stdout": "", "stderr": "connection lost"}])
    p.automation("ugoos_theater_kodi_status_poll")
    assert States(p)(HOST) == "off" and States(p)(OBSERVING) == "off"
    p.advance(30)
    p.automation("ugoos_theater_kodi_status_poll")
    assert p.timestamp(States(p)(EPOCH)) == p.now.timestamp()
    p.drain()
    assert p.commands().count("start") == 2 and p.service == "running"
    for _ in range(8):
        p.advance(30)
        p.automation("ugoos_theater_kodi_status_poll")
        p.drain()
    assert p.commands().count("start") == 2, "actual recovery must not disable command idempotency"


def reload_starts_fresh_observation(path):
    for kind in ("start", "automation_reloaded", "service_registered"):
        p = Package(path)
        established_pair(p)
        p.auto_events = True
        p.set_state(SONY, "off", age=7200)
        p.set_state(IDLE, "on")
        p.enqueue(RECONCILE)
        if kind == "start":
            p.start()
        else:
            p.event(kind, {"domain": "script", "service": RECONCILE})
        assert p.timestamp(States(p)(EPOCH)) == p.now.timestamp(), f"{kind} did not start a fresh epoch"
        assert States(p)(IDLE) == "off"
        p.drain()
        assert "stop" not in p.commands(), f"queued stop survived {kind} observation reset"
        p.advance(60)
        p.drain()
        assert p.service == "stopped"


def kodi_recovery_starts_fresh_observation(path):
    p = Package(path)
    established_pair(p)
    p.auto_events = True
    p.set_state(SONY, "off", age=7200)
    p.set_state(KODI, "unavailable")
    p.state_event(KODI, "idle")
    assert p.timestamp(States(p)(EPOCH)) == p.now.timestamp(), "Kodi availability recovery was not reconciled"
    p.drain()
    assert "stop" not in p.commands()
    p.advance(60)
    p.drain()
    assert p.service == "stopped"

def fresh_epoch_blocks_old_idle_episode(path):
    p = Package(path)
    established_pair(p)
    p.set_state(EPOCH, p.now.isoformat())
    p.set_state(IDLE, "on")
    p.run_script(POWER_OFF)
    assert not any(name == "media_player.turn_off" for name, _, _ in p.calls), \
        "old Kodi idle duration must not survive an observation reset"

def sony_failure_is_once_per_idle_episode(path):
    p = Package(path)
    established_pair(p)
    p.set_state(IDLE, "on")
    for _ in range(4):
        p.event("kodi_call_method_result", kodi_event())
        p.run_script(POWER_OFF)
        p.advance(15)
    requests = [call for call in p.calls if call[0] == "media_player.turn_off"]
    assert len(requests) == 1, f"failed Sony off request was retried {len(requests)} times in one idle episode"
    assert States(p)(SENT) == "on"
    assert "ugoos_theater_kodi_idle_poweroff" in p.notifications
    assert p.service == "running" and "stop" not in p.commands()


def sony_action_exception_is_not_silent(path):
    p = Package(path)
    established_pair(p)
    p.set_state(IDLE, "on")
    p.fail_actions.add("media_player.turn_off")
    try:
        p.run_script(POWER_OFF)
    except ServiceFailure:
        pass
    assert "ugoos_theater_kodi_idle_poweroff" in p.notifications, "Sony action exception skipped failure notification"
    assert States(p)(SENT) == "on"
    assert p.service == "running"


def stale_idle_evidence_does_not_rearm_sony(path):
    p = Package(path)
    established_pair(p)
    p.auto_events = True
    p.set_state(IDLE, "on")
    p.set_state(SENT, "on")
    p.set_state(PROBE_TIME, (p.now - timedelta(seconds=45)).isoformat())
    p.automation("ugoos_theater_kodi_idle_freshness")
    assert States(p)(SENT) == "on", "expiry was mistaken for genuine input activity and rearmed Sony off"
    p.event("kodi_call_method_result", kodi_event(result_ok=False))
    assert States(p)(SENT) == "on", "malformed/failed input evidence must not rearm the episode"
    p.event("kodi_call_method_result", kodi_event(False))
    assert States(p)(SENT) == "off", "fresh verified input activity must rearm the next idle episode"
    p.set_state(SENT, "on")
    p.state_event(KODI, "playing")
    assert States(p)(SENT) == "off", "real playback activity must rearm the next idle episode"


def failed_sony_latch_survives_restart(path):
    p = Package(path)
    p.set_state(SENT, "on")
    for name, config in p.package["input_boolean"].items():
        if "initial" in config:
            p.set_state(f"input_boolean.{name}", "on" if config["initial"] else "off")
    p.start()
    assert States(p)(SENT) == "on", "HA restart must not silently clear a failed episode latch"

def status_observation_does_not_claim_reconciliation(path):
    p = Package(path)
    established_pair(p)
    before = (p.now - timedelta(hours=1)).isoformat()
    p.set_state(RECONCILE_TIME, before)
    p.set_state(KODI, "unavailable")
    p.set_state(LAST_ERROR, "start readiness timed out")
    p.set_state("input_text.ugoos_theater_start_error", "start readiness timed out")
    p.notifications["ugoos_theater_kodi_lifecycle_start"] = "start readiness timed out"
    p.automation("ugoos_theater_kodi_status_poll")
    assert States(p)(RECONCILE_TIME) == before, "status observation falsely stamped successful reconciliation"
    assert "start readiness timed out" in States(p)(LAST_ERROR), "status poll cleared an unresolved start error"
    assert "ugoos_theater_kodi_lifecycle_start" in p.notifications


def already_running_still_requires_readiness(path):
    p = Package(path)
    established_pair(p)
    p.set_state(KODI, "unknown")
    before = (p.now - timedelta(hours=1)).isoformat()
    p.set_state(RECONCILE_TIME, before)
    p.run_script(RECONCILE)
    assert States(p)(RECONCILE_TIME) == before, "running-but-not-ready Kodi was certified as reconciled"
    assert "ugoos_theater_kodi_lifecycle_start" in p.notifications, "readiness failure was not reported"
    assert "start" not in p.commands(), "already-running Kodi must not be restarted as remediation"


def reconciliation_rechecks_status_after_readiness(path):
    p = Package(path)
    established_pair(p)
    p.service = "stopped"
    p.set_state(KODI, "unavailable")
    before = (p.now - timedelta(hours=1)).isoformat()
    p.set_state(RECONCILE_TIME, before)
    def apparent_readiness(fixture, _step):
        fixture.set_state(KODI, "idle")
        fixture.service = "stopped"
    p.wait_hook = apparent_readiness
    p.run_script(RECONCILE)
    assert States(p)(RECONCILE_TIME) == before, "a service lost during readiness wait was certified as running"
    assert "ugoos_theater_kodi_lifecycle_start" in p.notifications
    assert p.commands().count("status") >= 2, "no post-operation status verification was issued"


def operation_errors_clear_only_on_matching_convergence(path):
    p = Package(path)
    established_pair(p)
    p.set_state("input_text.ugoos_theater_start_error", "start readiness timeout")
    p.set_state("input_text.ugoos_theater_stop_error", "stop failed")
    p.set_state(LAST_ERROR, "start readiness timeout; stop failed")
    p.notifications["ugoos_theater_kodi_lifecycle_start"] = "start readiness timeout"
    p.notifications["ugoos_theater_kodi_lifecycle_stop"] = "stop failed"
    p.run_script(RECONCILE)
    assert "ugoos_theater_kodi_lifecycle_start" not in p.notifications, "verified running readiness did not clear start error"
    assert "ugoos_theater_kodi_lifecycle_stop" in p.notifications, "running convergence cleared an unrelated stop error"
    assert States(p)("input_text.ugoos_theater_start_error") == ""
    assert States(p)("input_text.ugoos_theater_stop_error") == "stop failed"
    assert "stop failed" in States(p)(LAST_ERROR)
    assert p.timestamp(States(p)(RECONCILE_TIME)) == p.now.timestamp()


def reachable_stale_probe_is_reported(path):
    p = Package(path)
    established_pair(p)
    p.set_state(IDLE, "on")
    p.set_state(PROBE_TIME, (p.now - timedelta(seconds=45)).isoformat())
    p.automation("ugoos_theater_kodi_idle_freshness")
    assert States(p)(IDLE) == "off"
    assert "ugoos_theater_kodi_idle_probe" in p.notifications, "reachable Kodi's stale probe expired silently"
    p.event("kodi_call_method_result", kodi_event())
    assert "ugoos_theater_kodi_idle_probe" not in p.notifications, "valid probe did not clear stale-probe notification"
    assert States(p)("input_text.ugoos_theater_idle_probe_error") == ""


def stale_probe_unreachable_and_fresh_epoch_are_quiet(path):
    for kodi_state, host, epoch_age in (("unavailable", "on", 3600), ("idle", "off", 3600), ("idle", "on", 0)):
        p = Package(path)
        established_pair(p)
        p.set_state(KODI, kodi_state)
        p.set_state(HOST, host)
        p.set_state(EPOCH, (p.now - timedelta(seconds=epoch_age)).isoformat())
        p.set_state(PROBE_TIME, (p.now - timedelta(seconds=45)).isoformat())
        p.set_state(IDLE, "on")
        p.automation("ugoos_theater_kodi_idle_freshness")
        assert States(p)(IDLE) == "off"
        assert "ugoos_theater_kodi_idle_probe" not in p.notifications, "unreachable Kodi or new epoch must not raise stale-probe alerts"


def valid_probe_clears_only_its_own_error(path):
    p = Package(path)
    established_pair(p)
    p.notifications["ugoos_theater_kodi_idle_probe"] = "malformed probe"
    p.notifications["ugoos_theater_kodi_idle_poweroff"] = "Sony power-off failed"
    p.set_state("input_text.ugoos_theater_idle_probe_error", "malformed probe")
    p.set_state("input_text.ugoos_theater_idle_poweroff_error", "Sony power-off failed")
    p.event("kodi_call_method_result", kodi_event(False))
    assert "ugoos_theater_kodi_idle_probe" not in p.notifications, "verified negative probe did not dismiss malformed-probe error"
    assert "ugoos_theater_kodi_idle_poweroff" in p.notifications, "input activity is not verified Sony-off recovery"
    assert States(p)("input_text.ugoos_theater_idle_probe_error") == ""
    assert "Sony power-off failed" in States(p)(LAST_ERROR)


def stderr_paths_are_actually_redacted(path):
    stderr = ("Identity file /config/.ssh/ugoos_kodi_lifecycle_ed25519 unavailable; "
              "/config/.ssh/known_hosts: permission denied")
    for operation in ("status", "start", "stop", "poll"):
        p = Package(path)
        established_pair(p)
        if operation == "start":
            p.service = "stopped"
        elif operation == "stop":
            p.set_state(SONY, "off", age=120)
        command = "status" if operation == "poll" else operation
        p.responses[command] = deque([{"returncode": 255, "stdout": "", "stderr": stderr}])
        if operation == "poll":
            p.automation("ugoos_theater_kodi_status_poll")
        else:
            p.run_script(RECONCILE)
        messages = list(p.notifications.values()) + [States(p)(LAST_ERROR)]
        assert any("[ssh-path]" in message for message in messages), f"{operation}: no sanitized diagnostic"
        assert not any("/config/.ssh/" in message for message in messages), f"{operation}: identity/known-host path leaked through regex"

def shell_action_exception_is_reported(path):
    for operation in ("status", "start", "stop", "poll"):
        p = Package(path)
        established_pair(p)
        if operation == "start":
            p.service = "stopped"
        elif operation == "stop":
            p.set_state(SONY, "off", age=120)
        command = "status" if operation == "poll" else operation
        p.fail_actions.add(f"shell_command.ugoos_theater_kodi_{command}")
        try:
            if operation == "poll":
                p.automation("ugoos_theater_kodi_status_poll")
            else:
                p.run_script(RECONCILE)
        except ServiceFailure:
            pass
        assert f"ugoos_theater_kodi_lifecycle_{command}" in p.notifications, \
            f"{operation}: shell action exception bypassed lifecycle error handling"
        expected_host = "on" if operation in ("start", "stop") else "off"
        assert States(p)(HOST) == expected_host, "only status observations determine host reachability"


def malformed_poll_preserves_reachable_host(path):
    p = Package(path)
    established_pair(p)
    p.responses["status"] = deque([{"returncode": 0, "stdout": "activating\n", "stderr": ""}])
    p.automation("ugoos_theater_kodi_status_poll")
    assert States(p)(HOST) == "on", "a malformed status on successful SSH is not host unreachability"
    assert States(p)(ACTUAL) == "unknown"
    assert "ugoos_theater_kodi_lifecycle_status" in p.notifications


def missing_entities_are_reported_without_rejecting_unknown_states(path):
    p = Package(path)
    established_pair(p)
    del p.entities[SONY]
    p.automation("ugoos_theater_kodi_status_poll")
    assert "ugoos_theater_kodi_configuration" in p.notifications, "missing paired entity was not reported"
    p.set_state(SONY, "unknown")
    p.automation("ugoos_theater_kodi_status_poll")
    assert "ugoos_theater_kodi_configuration" not in p.notifications, "configured-but-unknown Sony is not a missing entity"
    assert States(p)("sensor.ugoos_theater_desired_kodi_state") == "running"

def assert_policy(path, sony, age, keep, policy, expected, kodi="idle"):
    p = Package(path)
    established_pair(p)
    p.set_state(SONY, sony, age=age)
    p.set_state(KEEP, keep)
    p.set_state(KODI, kodi, age=3600)
    p.service = "running" if expected == "stopped" else "stopped"
    p.package["script"][RECONCILE]["variables"]["stop_when_display_off"] = policy
    if not policy:
        sensor = p.package["template"][0]["sensor"][0]
        sensor["state"] = sensor["state"].replace("stop_when_display_off = true", "stop_when_display_off = false")
    assert States(p)("sensor.ugoos_theater_desired_kodi_state") == expected, \
        f"sensor policy mismatch for {(sony, age, keep, policy)}"
    p.run_script(RECONCILE)
    assert p.service == expected, f"reconciliation policy mismatch for {(sony, age, keep, policy)}"


def unknown_sony_policy(path):
    for sony in ("unknown", "unavailable", "on", "idle", "playing", "paused"):
        assert_policy(path, sony, 7200, "off", True, "running")


def sony_off_interval_and_cancel(path):
    assert_policy(path, "off", 59, "off", True, "running")
    assert_policy(path, "off", 60, "off", True, "stopped")
    p = Package(path)
    established_pair(p)
    p.auto_events = True
    p.state_event(SONY, "off")
    p.advance(59)
    p.drain()
    assert "stop" not in p.commands(), "Sony-off trigger fired before sixty seconds"
    p.state_event(SONY, "on")
    p.state_event(SONY, "off")
    p.advance(59)
    p.drain()
    assert "stop" not in p.commands(), "canceled Sony-off interval was reused"
    p.advance(1)
    p.drain()
    assert p.service == "stopped"


def policy_override_precedence(path):
    assert_policy(path, "off", 7200, "on", True, "running")
    assert_policy(path, "off", 7200, "off", False, "running")
    assert_policy(path, "off", 7200, "on", False, "running")
    for kodi in ("playing", "paused"):
        assert_policy(path, "off", 7200, "off", True, "stopped", kodi)


def policy_sensor_and_reconciler_matrix(path):
    for sony, age in (("on", 0), ("off", 59), ("off", 60), ("unknown", 600), ("unavailable", 600)):
        for keep, policy, expected in (
            ("on", True, "running"), ("off", False, "running"),
            ("off", True, "stopped" if sony == "off" and age == 60 else "running"),
        ):
            assert_policy(path, sony, age, keep, policy, expected)


def idle_poweroff_gates(path):
    for kodi, idle_age, input_idle, freshness, sent, should_send in (
        ("idle", 1800, "on", 0, "off", True),
        ("idle", 1799, "on", 0, "off", False),
        ("idle", 3600, "off", 0, "off", False),
        ("idle", 3600, "on", 31, "off", False),
        ("idle", 3600, "on", 0, "on", False),
        ("playing", 3600, "on", 0, "off", False),
        ("paused", 3600, "on", 0, "off", False),
    ):
        p = Package(path)
        established_pair(p)
        p.set_state(KODI, kodi, age=idle_age)
        p.set_state(IDLE, input_idle)
        p.set_state(PROBE_TIME, (p.now - timedelta(seconds=freshness)).isoformat())
        p.set_state(SENT, sent)
        p.run_script(POWER_OFF)
        actual = any(call[0] == "media_player.turn_off" for call in p.calls)
        assert actual == should_send, f"idle power-off gate mismatch for {(kodi, idle_age, input_idle, freshness, sent)}"
    for keep, policy in (("on", True), ("off", False)):
        p = Package(path)
        established_pair(p)
        p.set_state(KEEP, keep)
        p.set_state(IDLE, "on")
        p.package["script"][RECONCILE]["variables"]["stop_when_display_off"] = policy
        p.run_script(POWER_OFF)
        assert any(call[0] == "media_player.turn_off" for call in p.calls), "stop overrides must not suppress idle Sony power-off"


def freshness_boundary(path):
    p = Package(path)
    established_pair(p)
    p.set_state(IDLE, "on")
    p.advance(30)
    p.automation("ugoos_theater_kodi_idle_freshness")
    assert States(p)(IDLE) == "on"
    p.advance(1)
    p.automation("ugoos_theater_kodi_idle_freshness")
    assert States(p)(IDLE) == "off"


def sony_off_precedes_normal_kodi_stop(path):
    p = Package(path)
    established_pair(p)
    p.auto_events = True
    p.set_state(IDLE, "on")
    def sony_confirms(fixture):
        assert States(fixture)(SENT) == "on", "episode must be latched before sending Sony off"
        fixture.state_event(SONY, "off")
    p.action_hooks["media_player.turn_off"] = sony_confirms
    p.run_script(POWER_OFF)
    assert "stop" not in p.commands()
    assert "ugoos_theater_kodi_idle_poweroff" not in p.notifications
    p.advance(59)
    p.drain()
    assert "stop" not in p.commands()
    p.advance(1)
    p.drain()
    assert p.service == "stopped", "Sony confirmation must use the ordinary sixty-second Kodi stop path"


def failed_service_is_reachable_and_notifies(path):
    p = Package(path)
    established_pair(p)
    p.service = "failed"
    p.automation("ugoos_theater_kodi_status_poll")
    assert States(p)(HOST) == "on"
    assert States(p)(ACTUAL) == "failed"
    assert "ugoos_theater_kodi_lifecycle_status" in p.notifications
    assert "failed" in States(p)(LAST_ERROR)

def static_ssh_deadline_boundary(path):
    commands = Package(path).package["shell_command"]
    assert set(commands) == {f"ugoos_theater_kodi_{word}" for word in ("start", "stop", "status")}
    for word in ("start", "stop", "status"):
        assert shlex.split(commands[f"ugoos_theater_kodi_{word}"]) == [
            "timeout", "15s", "ssh", "-F", "/config/.ssh/ugoos-kodi-lifecycle.conf",
            "ugoos-theater-lifecycle", word,
        ], f"{word} must be a static SSH invocation under the total fifteen-second deadline"


def main():
    path, scenario = sys.argv[1:]
    function = globals().get(scenario)
    if not callable(function) or scenario.startswith("_"):
        raise SystemExit(f"unknown fixture: {scenario}")
    function(path)


if __name__ == "__main__":
    try:
        main()
    except AssertionError as error:
        raise SystemExit(f"AssertionError ({sys.argv[-1]}): {error}")
