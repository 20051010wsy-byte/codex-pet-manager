from __future__ import annotations

import ipaddress
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Callable

from PIL import Image

from pet_core import ATLAS_SIZES


CLOUD_CACHE_KEY = "codex:persisted-atom:cloud-pet-artwork-cache"
CLOUD_STORAGE_KEY = "app://-"
MAX_ARTWORK_BYTES = 20 * 1024 * 1024
CLOUD_ID_PATTERN = re.compile(r"^pet_[A-Za-z0-9_-]{1,120}$")

_VENDOR_DIR = Path(__file__).resolve().parent / "vendor"
if str(_VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(_VENDOR_DIR))

from ccl_chromium_reader.ccl_chromium_localstorage import LocalStoreDb  # noqa: E402


@dataclass(frozen=True)
class CloudPetArtwork:
    id: str
    sprite_version: int
    spritesheet_url: str
    fingerprint: str = ""


@dataclass
class CloudSyncResult:
    discovered: int = 0
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    failed: int = 0
    storage_paths: list[Path] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.added or self.updated)


def default_cloud_cache_dir() -> Path:
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return local / "CodexPetManager" / "cloud-pets"


def discover_codex_local_storage_dirs(
    appdata: Path | None = None,
    local_appdata: Path | None = None,
) -> list[Path]:
    roaming = Path(appdata or os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    local = Path(
        local_appdata or os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")
    )
    candidates = [
        roaming
        / "Codex"
        / "web"
        / "Codex"
        / "Default"
        / "Local Storage"
        / "leveldb",
        local
        / "Codex"
        / "web"
        / "Codex"
        / "Default"
        / "Local Storage"
        / "leveldb",
    ]

    packages = local / "Packages"
    if packages.is_dir():
        for package in packages.glob("OpenAI.Codex*"):
            candidates.extend(
                package.glob(
                    "LocalCache/Roaming/*/web/*/Default/Local Storage/leveldb"
                )
            )

    result = []
    seen = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate
        key = str(resolved).casefold()
        if key not in seen and resolved.is_dir():
            seen.add(key)
            result.append(resolved)
    return sorted(result, key=lambda item: str(item).casefold())


def local_storage_signature(paths: list[Path]) -> tuple[tuple[str, int, int], ...]:
    entries = []
    for root in paths:
        if not root.is_dir():
            continue
        for path in root.iterdir():
            if not path.is_file():
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            entries.append((str(path), stat.st_size, stat.st_mtime_ns))
    return tuple(sorted(entries, key=lambda item: item[0].casefold()))


def _valid_remote_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urllib.parse.urlparse(value)
    return (
        parsed.scheme == "https"
        and parsed.hostname in {"chatgpt.com", "chatgpt-staging.com"}
        and parsed.username is None
        and parsed.password is None
    )


def parse_cloud_artworks(raw: str) -> list[CloudPetArtwork]:
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(payload, dict):
        return []

    records: dict[str, CloudPetArtwork] = {}
    pets = payload.get("pets")
    if not isinstance(pets, list):
        return []
    for item in pets:
        if not isinstance(item, dict):
            continue
        pet_id = item.get("id")
        if not isinstance(pet_id, str) or not CLOUD_ID_PATTERN.fullmatch(pet_id):
            continue
        try:
            version = int(item.get("spriteVersionNumber", 1))
        except (TypeError, ValueError):
            continue
        if version not in ATLAS_SIZES:
            continue
        url = item.get("spritesheetUrl")
        if not _valid_remote_url(url):
            continue
        fingerprint = item.get("spritesheetFingerprint")
        records[pet_id] = CloudPetArtwork(
            id=pet_id,
            sprite_version=version,
            spritesheet_url=url,
            fingerprint=str(fingerprint) if fingerprint else "",
        )
    return list(records.values())


def _read_artworks_from_store(
    path: Path,
    store_factory: Callable[[Path], object],
) -> list[CloudPetArtwork]:
    store = store_factory(path)
    try:
        candidates = []
        for storage_key in store.iter_storage_keys():
            if storage_key != CLOUD_STORAGE_KEY:
                continue
            if not store.contains_script_key(storage_key, CLOUD_CACHE_KEY):
                continue
            for record in store.iter_records_for_script_key(
                storage_key,
                CLOUD_CACHE_KEY,
                include_deletions=True,
                raise_on_no_result=False,
            ):
                if record.value:
                    candidates.append(record)
        if not candidates:
            return []
        latest = max(candidates, key=lambda record: record.leveldb_seq_number)
        return parse_cloud_artworks(latest.value)
    finally:
        store.close()


def read_cloud_artworks(
    paths: list[Path] | None = None,
    store_factory: Callable[[Path], object] | None = None,
) -> tuple[list[CloudPetArtwork], list[str]]:
    paths = paths if paths is not None else discover_codex_local_storage_dirs()
    store_factory = store_factory or LocalStoreDb
    artworks: dict[str, CloudPetArtwork] = {}
    errors = []
    for path in paths:
        try:
            for artwork in _read_artworks_from_store(path, store_factory):
                artworks[artwork.id] = artwork
        except Exception as error:
            errors.append(f"{path}: {error}")
    return list(artworks.values()), errors


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlparse(newurl)
        hostname = parsed.hostname or ""
        if parsed.scheme != "https" or hostname in {"localhost", "localhost.localdomain"}:
            raise urllib.error.HTTPError(
                newurl, code, "Unsafe pet artwork redirect", headers, fp
            )
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            address = None
        if address is not None and (address.is_private or address.is_loopback):
            raise urllib.error.HTTPError(
                newurl, code, "Unsafe pet artwork redirect", headers, fp
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_cloud_artwork(url: str) -> tuple[bytes, str, int]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "image/png,image/webp,image/*",
            "User-Agent": "CodexPetManager/1.0.5",
        },
    )
    opener = urllib.request.build_opener(_SafeRedirectHandler)
    with opener.open(request, timeout=20) as response:
        content_type = response.headers.get_content_type().lower()
        if content_type not in {"image/png", "image/webp", "application/octet-stream"}:
            raise ValueError(f"云端图集返回了不支持的内容类型：{content_type}")
        chunks = []
        size = 0
        while True:
            chunk = response.read(256 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_ARTWORK_BYTES:
                raise ValueError("云端图集超过 20 MB 限制")
            chunks.append(chunk)
    data = b"".join(chunks)
    with Image.open(BytesIO(data)) as image:
        image.verify()
    with Image.open(BytesIO(data)) as image:
        if image.format not in {"PNG", "WEBP"}:
            raise ValueError(f"云端图集格式不受支持：{image.format}")
        if image.size not in ATLAS_SIZES.values():
            raise ValueError(f"云端图集尺寸不受支持：{image.width}x{image.height}")
        version = next(
            version for version, dimensions in ATLAS_SIZES.items() if dimensions == image.size
        )
        extension = "png" if image.format == "PNG" else "webp"
    return data, extension, version


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_bytes(data)
    os.replace(temp, path)


def _atomic_json(path: Path, payload: dict) -> None:
    _atomic_write(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
    )


def _existing_fingerprint(folder: Path, artwork: CloudPetArtwork) -> str | None:
    metadata = folder / "pet.json"
    if not metadata.is_file() or not artwork.fingerprint:
        return None
    try:
        payload = json.loads(metadata.read_text(encoding="utf-8"))
        sheet = folder / str(payload.get("spritesheetPath", "spritesheet.webp"))
        if sheet.is_file() and payload.get("codexFingerprint") == artwork.fingerprint:
            return artwork.fingerprint
    except (OSError, TypeError, ValueError):
        pass
    return None


def sync_cloud_artworks(
    cache_dir: Path,
    artworks: list[CloudPetArtwork],
    fetch_bytes: Callable[[str], tuple[bytes, str, int]] = fetch_cloud_artwork,
) -> CloudSyncResult:
    result = CloudSyncResult(discovered=len(artworks))
    cache_dir.mkdir(parents=True, exist_ok=True)
    for artwork in artworks:
        folder = cache_dir / artwork.id
        existing = _existing_fingerprint(folder, artwork)
        if existing:
            result.unchanged += 1
            continue
        metadata_path = folder / "pet.json"
        existed = metadata_path.exists()
        try:
            data, extension, detected_version = fetch_bytes(artwork.spritesheet_url)
            if detected_version != artwork.sprite_version:
                raise ValueError(
                    f"云端图集版本不匹配：声明 {artwork.sprite_version}，实际 {detected_version}"
                )
            sheet_name = f"spritesheet.{extension}"
            _atomic_write(folder / sheet_name, data)
            payload = {
                "id": artwork.id,
                "displayName": f"云端桌宠 {artwork.id[-8:]}",
                "description": "从 Codex 云端人物缓存自动同步的只读副本。",
                "spriteVersionNumber": artwork.sprite_version,
                "spritesheetPath": sheet_name,
                "codexFingerprint": artwork.fingerprint,
            }
            _atomic_json(metadata_path, payload)
            if existed:
                result.updated += 1
            else:
                result.added += 1
        except Exception as error:
            result.failed += 1
            result.errors.append(f"{artwork.id}: {error}")
    return result


def sync_codex_cloud_pets(
    cache_dir: Path | None = None,
    paths: list[Path] | None = None,
    store_factory: Callable[[Path], object] | None = None,
    fetch_bytes: Callable[[str], tuple[bytes, str, int]] = fetch_cloud_artwork,
) -> CloudSyncResult:
    storage_paths = paths if paths is not None else discover_codex_local_storage_dirs()
    artworks, errors = read_cloud_artworks(storage_paths, store_factory=store_factory)
    result = sync_cloud_artworks(cache_dir or default_cloud_cache_dir(), artworks, fetch_bytes)
    result.storage_paths = storage_paths
    result.errors = errors + result.errors
    return result
