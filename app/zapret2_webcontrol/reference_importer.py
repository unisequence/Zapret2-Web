from __future__ import annotations

import re
import shlex
from dataclasses import dataclass

from .strategies import Strategy


@dataclass(frozen=True, slots=True)
class UciBlock:
    kind: str
    name: str
    options: dict[str, str]
    lists: dict[str, tuple[str, ...]]


def parse_uci_strategies(text: str) -> tuple[Strategy, ...]:
    """Convert `config strategy` blocks from the Linux/OpenWrt config.

    This intentionally parses only the portable strategy layer. Firewall
    queue numbers, nft/u32 expressions and shell hooks remain backend-owned.
    """

    result: list[Strategy] = []
    for block in _parse_blocks(text):
        if block.kind != "strategy":
            continue

        scripts = _script_lines(block.options.get("script", ""))
        portable_options = tuple(
            item for item in scripts
            if item.startswith(
                (
                    "--payload=",
                    "--in-range=",
                    "--out-range=",
                    "--hostlist-domains=",
                    "--lua-desync=",
                )
            )
        )
        unsupported_options = tuple(item for item in scripts if item not in portable_options)
        payload = _first_value(scripts, "--payload=")
        range_filters = tuple(
            item
            for item in scripts
            if item.startswith("--in-range=") or item.startswith("--out-range=")
        )
        lua_desync = tuple(
            item.removeprefix("--lua-desync=")
            for item in scripts
            if item.startswith("--lua-desync=")
        )
        protocols = _split_values(block.lists.get("protocol", ()))
        protocol = protocols[0] if protocols else "tcp"
        ports = _split_values(
            block.options.get("port", "")
            or block.options.get(f"{protocol}_port", "")
        )
        hostlists = tuple(
            _list_alias(item) for item in block.lists.get("hostlist", ())
        )
        excludes = tuple(
            _list_alias(item) for item in block.lists.get("hostlist_exclude", ())
        )
        notes: list[str] = []
        if range_filters:
            notes.append("Сохранены диапазонные фильтры из Linux-конфига.")
        if excludes:
            notes.append("Linux hostlist-исключения перенесены в общий профиль.")
        if not protocols:
            notes.append("В исходном блоке не указан protocol; выбран tcp.")
        if unsupported_options:
            notes.append("Есть параметры script, требующие ручной адаптации.")

        result.append(
            Strategy(
                id=_slugify(block.name),
                name=block.name,
                enabled=_as_bool(block.options.get("enabled", "1")),
                protocol=protocol,
                ports=ports,
                filter_l7=_split_values(block.lists.get("filter_l7", ())),
                hostlist=hostlists[0] if hostlists else None,
                payload=payload.removeprefix("--payload=") if payload else None,
                lua_desync=lua_desync,
                filter_l3=_split_values(block.lists.get("filter_l3", ())) or ("ipv4",),
                range_filters=range_filters,
                ordered_options=portable_options,
                unsupported_options=unsupported_options,
                hostlist_exclude=excludes,
                notes=" ".join(notes),
                source="linux-uci",
            )
        )
    return tuple(result)


def load_uci_strategies(path) -> tuple[Strategy, ...]:
    """Read a Linux/OpenWrt UCI config using UTF-8 with replacement."""

    return parse_uci_strategies(path.read_text(encoding="utf-8", errors="replace"))


def _parse_blocks(text: str) -> tuple[UciBlock, ...]:
    blocks: list[UciBlock] = []
    current: dict | None = None
    lines = iter(text.splitlines())
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        config = re.match(r"^config\s+(\S+)\s+(['\"])(.*?)\2\s*$", line)
        if config:
            if current:
                blocks.append(_make_block(current))
            current = {
                "kind": config.group(1),
                "name": config.group(3),
                "options": {},
                "lists": {},
            }
            continue
        if current is None:
            continue
        item = re.match(r"^(option|list)\s+(\S+)\s+(['\"])(.*)$", line)
        if not item:
            continue
        value = item.group(4)
        quote = item.group(3)
        if not _has_closing_quote(value, quote):
            continuation = [value]
            for next_line in lines:
                continuation.append(next_line)
                if _has_closing_quote(next_line, quote):
                    break
            value = "\n".join(continuation)
        value = _unquote(value, quote)
        key = item.group(2)
        if item.group(1) == "option":
            current["options"][key] = value
        else:
            current["lists"].setdefault(key, []).append(value)
    if current:
        blocks.append(_make_block(current))
    return tuple(blocks)


def _make_block(raw: dict) -> UciBlock:
    return UciBlock(
        kind=raw["kind"],
        name=raw["name"],
        options=dict(raw["options"]),
        lists={key: tuple(values) for key, values in raw["lists"].items()},
    )


def _has_closing_quote(value: str, quote: str) -> bool:
    return bool(re.search(rf"(?<!\\){re.escape(quote)}\s*$", value))


def _unquote(value: str, quote: str) -> str:
    value = value.strip()
    if value.endswith(quote) and not value.endswith("\\" + quote):
        value = value[:-1]
    if value.startswith(quote):
        value = value[1:]
    try:
        parsed = shlex.split(quote + value + quote, posix=True)
        return parsed[0] if parsed else ""
    except ValueError:
        return value.replace("\\" + quote, quote)


def _script_lines(script: str) -> tuple[str, ...]:
    try:
        return tuple(token for token in shlex.split(script) if token.startswith("--"))
    except ValueError:
        return tuple(line.strip() for line in script.splitlines() if line.strip().startswith("--"))


def _first_value(items: tuple[str, ...], prefix: str) -> str | None:
    return next((item for item in items if item.startswith(prefix)), None)


def _split_values(values) -> tuple[str, ...]:
    result: list[str] = []
    for value in values if not isinstance(values, str) else (values,):
        for item in value.split(","):
            item = item.strip()
            if item and item not in result:
                result.append(item)
    return tuple(result)


def _list_alias(value: str) -> str:
    return value.removeprefix("list_hosts_")


def _as_bool(value: str) -> bool:
    return value.strip().lower() not in {"0", "false", "off", "no", "disabled"}


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return normalized or "strategy"
