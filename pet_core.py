from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import unicodedata
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from PIL import Image


ATLAS_SIZES = {
    1: (1536, 1872),
    2: (1536, 2288),
}
METADATA_NAMES = {
    "pets": "pet.json",
    "avatars": "avatar.json",
    "cloud": "pet.json",
}


@dataclass
class PetRecord:
    id: str
    display_name: str
    description: str
    sprite_version: int
    sheet_path: Path | None
    metadata_path: Path | None
    enabled: bool
    locations: dict[str, Path] = field(default_factory=dict)
    width: int = 0
    height: int = 0
    bytes: int = 0
    updated_at: float = 0
    valid: bool = False
    error: str = ""

    @property
    def status_label(self) -> str:
        if not self.valid:
            return "文件异常"
        if self.is_cloud:
            return "云端同步"
        return "已启用" if self.enabled else "已停用"

    @property
    def version_label(self) -> str:
        if self.sprite_version == 2:
            return "v2 · 完整朝向"
        return "v1 · 九状态兼容"

    @property
    def source_label(self) -> str:
        keys = sorted(self.locations)
        if keys == ["avatars", "pets"]:
            return "Mini & Pets"
        if keys == ["pets"]:
            return "Pets"
        if keys == ["avatars"]:
            return "Mini"
        if keys == ["cloud"]:
            return "Codex 云端缓存"
        return "本地"

    @property
    def is_cloud(self) -> bool:
        return bool(self.locations) and set(self.locations) == {"cloud"}

    @property
    def primary_dir(self) -> Path | None:
        for key in ("pets", "avatars"):
            if key in self.locations:
                return self.locations[key]
        return self.sheet_path.parent if self.sheet_path else None


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temp, path)


def safe_relative(value: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("素材路径为空")
    if "\\" in value or ":" in value:
        raise ValueError("素材路径包含不支持的字符")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("素材路径越界")
    return relative


def inspect_sprite(path: Path, version: int) -> tuple[int, int, int]:
    if not path.is_file():
        raise FileNotFoundError(f"缺少人物图集：{path.name}")
    if version not in ATLAS_SIZES:
        raise ValueError(f"不支持 spriteVersionNumber={version}")
    with Image.open(path) as image:
        if image.size != ATLAS_SIZES[version]:
            raise ValueError(
                f"图集尺寸应为 {ATLAS_SIZES[version][0]}x{ATLAS_SIZES[version][1]}，"
                f"实际为 {image.width}x{image.height}"
            )
        if image.mode not in ("RGBA", "LA"):
            image = image.convert("RGBA")
        alpha = image.getchannel("A")
        if alpha.getextrema() == (255, 255):
            raise ValueError("图集没有透明背景")
        return image.width, image.height, path.stat().st_size


def metadata_candidates(root: Path) -> list[Path]:
    found = []
    for name in METADATA_NAMES.values():
        found.extend(root.rglob(name))
    result = []
    for path in sorted(set(found)):
        parent = path.parent
        if any(other != parent and other in parent.parents for other in result):
            continue
        result.append(parent)
    return sorted(result)


def metadata_directories(root: Path, metadata_name: str) -> list[Path]:
    if not root.is_dir():
        return []
    found = []
    for path in root.rglob(metadata_name):
        if not path.is_file():
            continue
        folder = path.parent
        if any(other != folder and other in folder.parents for other in found):
            continue
        found.append(folder)
    return sorted(found)


def slugify(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_value).strip("-").lower()
    if slug:
        return slug[:60]
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]
    return "pet-" + digest


class PetRepository:
    def __init__(
        self,
        codex_home: Path | None = None,
        pets_dir: Path | None = None,
        avatars_dir: Path | None = None,
        cloud_dir: Path | None = None,
        disabled_dir: Path | None = None,
    ):
        configured_home = (
            codex_home
            or os.environ.get("CODEX_PET_MANAGER_HOME")
            or os.environ.get("CODEX_HOME")
            or Path.home() / ".codex"
        )
        self.codex_home = Path(configured_home).expanduser().resolve()
        self.pets_dir = Path(pets_dir or self.codex_home / "pets")
        self.avatars_dir = Path(avatars_dir or self.codex_home / "avatars")
        local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        if cloud_dir is not None:
            configured_cloud_dir = cloud_dir
        elif codex_home is not None:
            configured_cloud_dir = self.codex_home / "cloud-pets"
        else:
            configured_cloud_dir = (
                os.environ.get("CODEX_PET_MANAGER_CLOUD_CACHE")
                or local / "CodexPetManager" / "cloud-pets"
            )
        self.cloud_dir = Path(configured_cloud_dir)
        self.disabled_dir = Path(
            disabled_dir or self.codex_home / "pet-manager" / "disabled"
        )
        self.last_errors: list[str] = []

    def ensure_directories(self) -> None:
        self.pets_dir.mkdir(parents=True, exist_ok=True)
        self.avatars_dir.mkdir(parents=True, exist_ok=True)
        self.cloud_dir.mkdir(parents=True, exist_ok=True)
        self.disabled_dir.mkdir(parents=True, exist_ok=True)

    def _load_candidate(self, folder: Path, kind: str) -> PetRecord | None:
        metadata_path = folder / METADATA_NAMES[kind]
        if not metadata_path.is_file():
            return None
        try:
            data = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            self.last_errors.append(f"{metadata_path}: {error}")
            error_id = folder.name if kind != "cloud" else f"cloud:{folder.name}"
            return PetRecord(
                id=error_id,
                display_name=folder.name,
                description="",
                sprite_version=1,
                sheet_path=None,
                metadata_path=metadata_path,
                enabled=kind in METADATA_NAMES,
                locations={kind: folder},
                error=f"人物配置无法读取：{error}",
            )

        pet_id = str(data.get("id") or folder.name)
        if kind == "cloud":
            pet_id = f"cloud:{pet_id}"
        display_name = str(data.get("displayName") or pet_id)
        description = str(data.get("description") or "")
        try:
            version = int(data.get("spriteVersionNumber", 1))
            sheet_relative = safe_relative(data.get("spritesheetPath", "spritesheet.webp"))
            sheet_path = folder / sheet_relative
            width, height, size = inspect_sprite(sheet_path, version)
            valid = True
            error = ""
        except (OSError, ValueError, TypeError) as exc:
            version = int(data.get("spriteVersionNumber", 1) or 1)
            sheet_path = None
            width = height = size = 0
            valid = False
            error = str(exc)
        updated = max(
            metadata_path.stat().st_mtime,
            sheet_path.stat().st_mtime if sheet_path and sheet_path.exists() else 0,
        )
        return PetRecord(
            id=pet_id,
            display_name=display_name,
            description=description,
            sprite_version=version,
            sheet_path=sheet_path,
            metadata_path=metadata_path,
            enabled=True,
            locations={kind: folder},
            width=width,
            height=height,
            bytes=size,
            updated_at=updated,
            valid=valid,
            error=error,
        )

    def scan(self) -> list[PetRecord]:
        self.ensure_directories()
        self.last_errors = []
        records: dict[str, PetRecord] = {}
        for kind, root in (
            ("pets", self.pets_dir),
            ("avatars", self.avatars_dir),
            ("cloud", self.cloud_dir),
        ):
            for folder in metadata_directories(root, METADATA_NAMES[kind]):
                if kind == "cloud" and not folder.name.startswith("pet_"):
                    continue
                record = self._load_candidate(folder, kind)
                if record is None:
                    continue
                if record.id in records:
                    current = records[record.id]
                    current.locations[kind] = folder
                    if kind == "pets":
                        current.display_name = record.display_name
                        current.description = record.description
                        current.sprite_version = record.sprite_version
                        current.sheet_path = record.sheet_path
                        current.metadata_path = record.metadata_path
                        current.width = record.width
                        current.height = record.height
                        current.bytes = record.bytes
                        current.updated_at = max(current.updated_at, record.updated_at)
                        current.valid = record.valid
                        current.error = record.error
                else:
                    records[record.id] = record

        disabled_entries = []
        for store in sorted(self.disabled_dir.iterdir()):
            if not store.is_dir():
                continue
            record = None
            locations = {}
            for kind in ("pets", "avatars"):
                folder = store / kind
                if not folder.is_dir():
                    continue
                candidate = self._load_candidate(folder, kind)
                if candidate:
                    candidate.enabled = False
                    locations[kind] = folder
                    if record is None or kind == "pets":
                        record = candidate
            if record:
                record.enabled = False
                record.locations = locations
                if record.id not in records:
                    records[record.id] = record
                disabled_entries.append(record.id)

        return sorted(
            records.values(),
            key=lambda item: (not item.enabled, item.display_name.casefold(), item.id),
        )

    def signature(self) -> tuple[tuple[str, int, int], ...]:
        entries = []
        roots = (
            (self.pets_dir, METADATA_NAMES["pets"]),
            (self.avatars_dir, METADATA_NAMES["avatars"]),
            (self.cloud_dir, METADATA_NAMES["cloud"]),
            (self.disabled_dir, METADATA_NAMES["pets"]),
            (self.disabled_dir, METADATA_NAMES["avatars"]),
        )
        for root, name in roots:
            if not root.is_dir():
                continue
            for path in root.rglob(name):
                try:
                    stat = path.stat()
                except OSError:
                    continue
                entries.append((str(path), stat.st_size, stat.st_mtime_ns))
        return tuple(sorted(entries, key=lambda item: item[0].casefold()))

    def find(self, pet_id: str) -> PetRecord | None:
        return next((item for item in self.scan() if item.id == pet_id), None)

    def disable(self, pet_id: str) -> None:
        record = self.find(pet_id)
        if record and record.is_cloud:
            raise ValueError("Codex 云端人物为只读缓存，请在 Codex 设置中管理。")
        if not record or not record.enabled:
            return
        store = self.disabled_dir / pet_id
        if store.exists():
            raise FileExistsError(f"停用目录已存在：{store}")
        store.mkdir(parents=True)
        moved = []
        try:
            for kind, source in record.locations.items():
                target = store / kind
                shutil.move(str(source), str(target))
                moved.append((kind, source, target))
        except Exception:
            for _kind, source, target in reversed(moved):
                if target.exists() and not source.exists():
                    shutil.move(str(target), str(source))
            if store.exists() and not any(store.iterdir()):
                store.rmdir()
            raise

    def enable(self, pet_id: str) -> None:
        store = self.disabled_dir / pet_id
        if not store.is_dir():
            raise FileNotFoundError(f"找不到已停用人物：{pet_id}")
        moved = []
        try:
            for kind in ("pets", "avatars"):
                source = store / kind
                if not source.is_dir():
                    continue
                destination = (self.pets_dir if kind == "pets" else self.avatars_dir) / pet_id
                if destination.exists():
                    raise FileExistsError(f"启用目标已存在：{destination}")
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(source), str(destination))
                moved.append((kind, source, destination))
        except Exception:
            for _kind, source, destination in reversed(moved):
                if destination.exists() and not source.exists():
                    shutil.move(str(destination), str(source))
            raise
        if store.exists() and not any(store.iterdir()):
            store.rmdir()

    def delete(self, pet_id: str) -> None:
        record = self.find(pet_id)
        if record and record.is_cloud:
            raise ValueError("Codex 云端人物为只读缓存，不能从管理台删除。")
        for folder in (
            self.pets_dir / pet_id,
            self.avatars_dir / pet_id,
            self.disabled_dir / pet_id,
        ):
            if folder.exists():
                shutil.rmtree(folder)

    def update_metadata(self, pet_id: str, display_name: str, description: str) -> None:
        record = self.find(pet_id)
        if not record:
            raise FileNotFoundError(pet_id)
        if record.is_cloud:
            raise ValueError("Codex 云端人物为只读缓存，请在 Codex 设置中修改。")
        if not display_name.strip():
            raise ValueError("人物名称不能为空")
        for metadata_path in self._metadata_paths(record):
            data = json.loads(metadata_path.read_text(encoding="utf-8"))
            data["displayName"] = display_name.strip()
            data["description"] = description.strip()
            atomic_json(metadata_path, data)

    def _metadata_paths(self, record: PetRecord) -> Iterable[Path]:
        for kind, folder in record.locations.items():
            path = folder / METADATA_NAMES[kind]
            if path.is_file():
                yield path

    def _unique_id(self, requested: str) -> str:
        base = slugify(requested or "pet")
        candidate = base
        counter = 2
        while (
            (self.pets_dir / candidate).exists()
            or (self.avatars_dir / candidate).exists()
            or (self.disabled_dir / candidate).exists()
        ):
            candidate = f"{base}-{counter}"
            counter += 1
        return candidate

    def import_folder(self, source: Path) -> list[str]:
        source = Path(source)
        candidates = metadata_candidates(source) if source.is_dir() else []
        if not candidates:
            metadata = source / "pet.json"
            if metadata.is_file():
                candidates = [source]
        if not candidates:
            raise ValueError("文件夹中没有 pet.json 或 avatar.json")
        imported = []
        for candidate in candidates:
            imported.append(self._install_candidate(candidate))
        return imported

    def import_zip(self, archive: Path) -> list[str]:
        archive = Path(archive)
        self.ensure_directories()
        with tempfile.TemporaryDirectory(
            prefix="import-", dir=str(self.codex_home / "pet-manager")
        ) as temp_dir:
            root = Path(temp_dir)
            with zipfile.ZipFile(archive) as source:
                for info in source.infolist():
                    target = root / info.filename
                    resolved = target.resolve()
                    if not resolved.is_relative_to(root.resolve()):
                        raise ValueError("ZIP 包含越界路径")
                    if info.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with source.open(info) as reader, target.open("wb") as writer:
                        shutil.copyfileobj(reader, writer)
            return self.import_folder(root)

    def _install_candidate(self, folder: Path) -> str:
        metadata_name = next(
            (name for name in METADATA_NAMES.values() if (folder / name).is_file()),
            None,
        )
        if metadata_name is None:
            raise ValueError("人物目录缺少配置文件")
        raw = json.loads((folder / metadata_name).read_text(encoding="utf-8"))
        display_name = str(raw.get("displayName") or raw.get("id") or folder.name)
        description = str(raw.get("description") or "")
        version = int(raw.get("spriteVersionNumber", 1))
        sheet_relative = safe_relative(raw.get("spritesheetPath", "spritesheet.webp"))
        inspect_sprite(folder / sheet_relative, version)
        requested_id = str(raw.get("id") or display_name)
        pet_id = self._unique_id(requested_id)

        pet_target = self.pets_dir / pet_id
        avatar_target = self.avatars_dir / pet_id
        shutil.copytree(folder, pet_target)
        shutil.copytree(folder, avatar_target)

        pet_metadata = pet_target / "pet.json"
        if not pet_metadata.exists():
            pet_metadata = pet_target / metadata_name
        data = json.loads(pet_metadata.read_text(encoding="utf-8"))
        data["id"] = pet_id
        data["displayName"] = display_name
        data["description"] = description
        data["spriteVersionNumber"] = version
        data["spritesheetPath"] = str(sheet_relative).replace("\\", "/")
        atomic_json(pet_target / "pet.json", data)
        atomic_json(avatar_target / "avatar.json", data)
        old_metadata = pet_target / metadata_name
        if old_metadata != pet_metadata and old_metadata.exists():
            old_metadata.unlink()
        return pet_id
