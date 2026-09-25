from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import replace
from pathlib import Path
from typing import Iterable

from .strategies import Strategy


class StrategyValidationError(ValueError):
    """Raised when a user-provided strategy override is unsafe or malformed."""


class StrategyStore:
    """Persist reference overrides and user-created strategies atomically."""

    VERSION = 1
    EDITABLE_FIELDS = {
        "name",
        "enabled",
        "protocol",
        "ports",
        "filter_l7",
        "hostlist",
        "ordered_options",
    }
    FORBIDDEN_OPTIONS = (
        "--new",
        "--wf-",
        "--lua-init",
        "--blob=",
        "--filter-tcp",
        "--filter-udp",
        "--filter-l3",
        "--filter-l7",
        "--hostlist=",
        "--hostlist-exclude=",
    )
    _PORT_RE = re.compile(r"^(\d{1,5})(?:-(\d{1,5}))?$")
    _TOKEN_RE = re.compile(r"^[a-z0-9_-]+$")
    _HOSTLIST_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
    _ID_RE = re.compile(r"^[a-z0-9_]{1,100}$")

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()

    def apply(self, strategies: Iterable[Strategy]) -> tuple[Strategy, ...]:
        overrides, custom = self._read()
        reference = tuple(
            self._apply_patch(strategy, overrides.get(strategy.id, {}))
            for strategy in strategies
        )
        return reference + custom

    def update(
        self,
        strategies: Iterable[Strategy],
        strategy_id: str,
        patch: dict,
    ) -> Strategy:
        with self._lock:
            reference_by_id = {strategy.id: strategy for strategy in strategies}
            overrides, custom = self._read()
            validated = self._validate_patch(patch)

            custom_by_id = {strategy.id: index for index, strategy in enumerate(custom)}
            custom_index = custom_by_id.get(strategy_id)
            if custom_index is not None:
                updated = self._apply_patch(custom[custom_index], validated)
                mutable_custom = list(custom)
                mutable_custom[custom_index] = updated
                self._write(overrides, tuple(mutable_custom))
                return updated

            base = reference_by_id.get(strategy_id)
            if base is None:
                raise KeyError(strategy_id)
            merged = dict(overrides.get(strategy_id, {}))
            merged.update(validated)
            updated = self._apply_patch(base, merged)
            compact = {
                field: value
                for field, value in merged.items()
                if getattr(updated, field) != getattr(base, field)
            }
            if compact:
                overrides[strategy_id] = compact
            else:
                overrides.pop(strategy_id, None)
            self._write(overrides, custom)
            return updated

    def create(self, strategies: Iterable[Strategy], payload: object) -> Strategy:
        with self._lock:
            reference = tuple(strategies)
            overrides, custom = self._read()
            fields = self._validate_create(payload)
            existing_ids = {strategy.id for strategy in reference + custom}
            strategy_id = self._new_id(fields["name"], existing_ids)
            strategy = self._custom_strategy(strategy_id, fields)
            self._write(overrides, custom + (strategy,))
            return strategy

    def delete(self, strategies: Iterable[Strategy], strategy_id: str) -> Strategy:
        with self._lock:
            if any(strategy.id == strategy_id for strategy in strategies):
                raise StrategyValidationError(
                    "Эталонную стратегию нельзя удалить; её можно выключить"
                )
            overrides, custom = self._read()
            removed = next((item for item in custom if item.id == strategy_id), None)
            if removed is None:
                raise KeyError(strategy_id)
            self._write(
                overrides,
                tuple(item for item in custom if item.id != strategy_id),
            )
            return removed

    def reset(self) -> None:
        with self._lock:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass

    def _read(self) -> tuple[dict[str, dict], tuple[Strategy, ...]]:
        if not self.path.is_file():
            return {}, ()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RuntimeError(f"Не удалось прочитать настройки стратегий: {error}") from error
        if not isinstance(payload, dict) or payload.get("version") != self.VERSION:
            raise RuntimeError("Неподдерживаемый формат настроек стратегий")
        raw_overrides = payload.get("overrides", {})
        if not isinstance(raw_overrides, dict):
            raise RuntimeError("Некорректный раздел overrides в настройках стратегий")
        overrides = {
            str(strategy_id): self._validate_patch(patch)
            for strategy_id, patch in raw_overrides.items()
        }
        raw_custom = payload.get("custom", [])
        if not isinstance(raw_custom, list):
            raise RuntimeError("Некорректный раздел custom в настройках стратегий")
        custom: list[Strategy] = []
        seen_ids: set[str] = set()
        for record in raw_custom:
            if not isinstance(record, dict):
                raise RuntimeError("Некорректная пользовательская стратегия")
            strategy_id = record.get("id")
            if (
                not isinstance(strategy_id, str)
                or not self._ID_RE.fullmatch(strategy_id)
                or strategy_id in seen_ids
            ):
                raise RuntimeError("Некорректный id пользовательской стратегии")
            seen_ids.add(strategy_id)
            try:
                fields = self._validate_create(
                    {key: value for key, value in record.items() if key != "id"}
                )
            except StrategyValidationError as error:
                raise RuntimeError(
                    f"Некорректная пользовательская стратегия {strategy_id}: {error}"
                ) from error
            custom.append(self._custom_strategy(strategy_id, fields))
        return overrides, tuple(custom)

    def _write(
        self,
        overrides: dict[str, dict],
        custom: tuple[Strategy, ...] = (),
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        payload = {
            "version": self.VERSION,
            "overrides": overrides,
            "custom": [self._custom_record(strategy) for strategy in custom],
        }
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.path)

    @classmethod
    def _validate_patch(cls, patch: object) -> dict:
        if not isinstance(patch, dict):
            raise StrategyValidationError("Изменения стратегии должны быть JSON-объектом")
        unknown = set(patch) - cls.EDITABLE_FIELDS
        if unknown:
            raise StrategyValidationError(
                "Нередактируемые поля: " + ", ".join(sorted(unknown))
            )

        result: dict = {}
        if "name" in patch:
            result["name"] = cls._validate_name(patch["name"])
        if "enabled" in patch:
            if not isinstance(patch["enabled"], bool):
                raise StrategyValidationError("enabled должен быть boolean")
            result["enabled"] = patch["enabled"]
        if "protocol" in patch:
            if patch["protocol"] not in {"tcp", "udp"}:
                raise StrategyValidationError("protocol должен быть tcp или udp")
            result["protocol"] = patch["protocol"]
        if "ports" in patch:
            ports = cls._string_list(patch["ports"], "ports", allow_empty=False)
            for token in ports:
                match = cls._PORT_RE.fullmatch(token)
                if not match:
                    raise StrategyValidationError(f"Некорректный порт или диапазон: {token}")
                first = int(match.group(1))
                last = int(match.group(2) or first)
                if first < 1 or last > 65535 or first > last:
                    raise StrategyValidationError(f"Порт вне допустимого диапазона: {token}")
            result["ports"] = ports
        if "filter_l7" in patch:
            values = cls._string_list(patch["filter_l7"], "filter_l7")
            if any(not cls._TOKEN_RE.fullmatch(value) for value in values):
                raise StrategyValidationError("filter_l7 содержит недопустимый идентификатор")
            result["filter_l7"] = values
        if "hostlist" in patch:
            hostlist = patch["hostlist"]
            if hostlist is not None and (
                not isinstance(hostlist, str)
                or len(hostlist) > 100
                or not cls._HOSTLIST_RE.fullmatch(hostlist)
            ):
                raise StrategyValidationError("Некорректное имя hostlist")
            result["hostlist"] = hostlist
        if "ordered_options" in patch:
            options = cls._string_list(patch["ordered_options"], "ordered_options")
            if len(options) > 100:
                raise StrategyValidationError("Слишком много параметров стратегии")
            for option in options:
                if len(option) > 2048 or "\n" in option or "\r" in option or "\0" in option:
                    raise StrategyValidationError("Некорректный параметр стратегии")
                if not option.startswith("--"):
                    raise StrategyValidationError(f"Параметр должен начинаться с --: {option}")
                if any(option == prefix or option.startswith(prefix) for prefix in cls.FORBIDDEN_OPTIONS):
                    raise StrategyValidationError(
                        f"Параметр управляется бэкендом и не редактируется здесь: {option}"
                    )
            result["ordered_options"] = options
        return result

    @classmethod
    def _validate_create(cls, payload: object) -> dict:
        if not isinstance(payload, dict):
            raise StrategyValidationError("Стратегия должна быть JSON-объектом")
        validated = cls._validate_patch(payload)
        if "name" not in validated:
            raise StrategyValidationError("Укажите название стратегии")
        validated.setdefault("enabled", True)
        validated.setdefault("protocol", "tcp")
        validated.setdefault("ports", ("443",))
        validated.setdefault("filter_l7", ())
        validated.setdefault("hostlist", None)
        validated.setdefault("ordered_options", ())
        return validated

    @staticmethod
    def _validate_name(value: object) -> str:
        if not isinstance(value, str):
            raise StrategyValidationError("Название стратегии должно быть строкой")
        normalized = value.strip()
        if not normalized or len(normalized) > 80 or any(
            character in normalized for character in "\r\n\0"
        ):
            raise StrategyValidationError("Некорректное название стратегии")
        return normalized

    @staticmethod
    def _string_list(value: object, field: str, *, allow_empty: bool = True) -> tuple[str, ...]:
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise StrategyValidationError(f"{field} должен быть массивом строк")
        normalized = tuple(item.strip() for item in value)
        if any(not item for item in normalized) or (not allow_empty and not normalized):
            raise StrategyValidationError(f"{field} не должен содержать пустые значения")
        return normalized

    @staticmethod
    def _apply_patch(strategy: Strategy, patch: dict) -> Strategy:
        if not patch:
            return strategy
        updated = replace(strategy, **patch)
        if "ordered_options" not in patch:
            return updated
        options = updated.ordered_options
        payload_option = next(
            (item for item in options if item.startswith("--payload=")),
            None,
        )
        return replace(
            updated,
            payload=payload_option.removeprefix("--payload=") if payload_option else None,
            lua_desync=tuple(
                item.removeprefix("--lua-desync=")
                for item in options
                if item.startswith("--lua-desync=")
            ),
            range_filters=tuple(
                item
                for item in options
                if item.startswith(("--in-range=", "--out-range="))
            ),
        )

    @classmethod
    def _custom_strategy(cls, strategy_id: str, fields: dict) -> Strategy:
        strategy = Strategy(
            id=strategy_id,
            name=fields["name"],
            enabled=fields["enabled"],
            protocol=fields["protocol"],
            ports=fields["ports"],
            filter_l7=fields["filter_l7"],
            hostlist=fields["hostlist"],
            payload=None,
            lua_desync=(),
            ordered_options=fields["ordered_options"],
            notes="Пользовательская стратегия.",
            source="custom",
        )
        return cls._apply_patch(strategy, {"ordered_options": fields["ordered_options"]})

    @staticmethod
    def _custom_record(strategy: Strategy) -> dict:
        return {
            "id": strategy.id,
            "name": strategy.name,
            "enabled": strategy.enabled,
            "protocol": strategy.protocol,
            "ports": list(strategy.ports),
            "filter_l7": list(strategy.filter_l7),
            "hostlist": strategy.hostlist,
            "ordered_options": list(strategy.ordered_options),
        }

    @staticmethod
    def _new_id(name: str, existing_ids: set[str]) -> str:
        slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "strategy"
        base = f"custom_{slug[:80]}"
        candidate = base
        suffix = 2
        while candidate in existing_ids:
            candidate = f"{base[:94]}_{suffix}"
            suffix += 1
        return candidate
