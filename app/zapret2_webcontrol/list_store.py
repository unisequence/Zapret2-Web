from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path


class ListValidationError(ValueError):
    """Raised when list content or a list identifier is invalid."""


@dataclass(frozen=True, slots=True)
class ListSpec:
    id: str
    label: str
    filename: str
    description: str


@dataclass(frozen=True, slots=True)
class ListInfo:
    id: str
    label: str
    description: str
    filename: str
    source: str
    path: str
    exists: bool
    entries: int
    size: int
    editable: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ListDocument:
    info: ListInfo
    content: str

    def to_dict(self) -> dict:
        return {"info": self.info.to_dict(), "content": self.content}


LIST_SPECS = (
    ListSpec("auto", "Автолист", "zapret_hosts_auto.txt", "Автоматически обнаруженные хосты."),
    ListSpec("user", "Пользовательский", "zapret_hosts_user.txt", "Домены, добавленные пользователем."),
    ListSpec("user_exclude", "Исключения", "zapret_hosts_user_exclude.txt", "Домены, которые не нужно обрабатывать."),
    ListSpec("youtube", "YouTube", "zapret_hosts_youtube.txt", "Домены YouTube и Google Video."),
    ListSpec("discord", "Discord", "zapret_hosts_discord.txt", "Домены Discord."),
)


class ListStore:
    MAX_BYTES = 2 * 1024 * 1024
    MAX_LINE = 4096

    def __init__(self, directory: Path, *, bundled_youtube: Path | None = None) -> None:
        self.directory = directory
        self.bundled_youtube = bundled_youtube
        self._specs = {spec.id: spec for spec in LIST_SPECS}

    def infos(self) -> tuple[ListInfo, ...]:
        return tuple(self._info(spec) for spec in LIST_SPECS)

    def read(self, list_id: str) -> ListDocument:
        spec = self._get_spec(list_id)
        info = self._info(spec)
        path = Path(info.path)
        if not info.exists:
            content = ""
        else:
            try:
                content = path.read_text(encoding="utf-8-sig", errors="strict")
            except (OSError, UnicodeDecodeError) as error:
                raise RuntimeError(f"Не удалось прочитать список {spec.label}: {error}") from error
        return ListDocument(info=info, content=content)

    def update(self, list_id: str, content: object) -> ListDocument:
        spec = self._get_spec(list_id)
        normalized = self._validate_content(content)
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / spec.filename
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(normalized, encoding="utf-8", newline="\n")
        os.replace(temporary, path)
        return self.read(list_id)

    def _info(self, spec: ListSpec) -> ListInfo:
        runtime_path = self.directory / spec.filename
        source = "runtime"
        path = runtime_path
        if not runtime_path.is_file() and spec.id == "youtube" and self.bundled_youtube:
            source = "bundled"
            path = self.bundled_youtube
        exists = path.is_file()
        size = path.stat().st_size if exists else 0
        entries = 0
        if exists:
            try:
                entries = sum(
                    1
                    for line in path.read_text(
                        encoding="utf-8-sig", errors="replace"
                    ).splitlines()
                    if line.strip() and not line.lstrip().startswith("#")
                )
            except OSError:
                entries = 0
        return ListInfo(
            id=spec.id,
            label=spec.label,
            description=spec.description,
            filename=spec.filename,
            source=source if exists else "empty",
            path=str(path),
            exists=exists,
            entries=entries,
            size=size,
        )

    def _get_spec(self, list_id: str) -> ListSpec:
        try:
            return self._specs[list_id]
        except KeyError as error:
            raise KeyError(list_id) from error

    @classmethod
    def _validate_content(cls, content: object) -> str:
        if not isinstance(content, str):
            raise ListValidationError("content должен быть строкой")
        if "\0" in content:
            raise ListValidationError("Список содержит недопустимый нулевой байт")
        normalized = content.replace("\r\n", "\n").replace("\r", "\n")
        encoded = normalized.encode("utf-8")
        if len(encoded) > cls.MAX_BYTES:
            raise ListValidationError("Список превышает допустимый размер 2 МБ")
        if any(len(line) > cls.MAX_LINE for line in normalized.splitlines()):
            raise ListValidationError("Строка списка превышает 4096 символов")
        if normalized and not normalized.endswith("\n"):
            normalized += "\n"
        return normalized
