import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

import requests

appdata_root = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
legacy_appdata = appdata_root / "FunnyExecutor"
appdata = appdata_root / "AkazExecutor"
appdata.mkdir(parents=True, exist_ok=True)

OFFSETS_BASE_URL = "https://offsets.imtheo.lol"
REQUEST_TIMEOUT_SECONDS = 8
CACHE_SCHEMA = 2

offsets_to_copy = {
    "fake_datamodel_ptr": ["FakeDataModel", "Pointer"],
    "real_datamodel_ptr": ["FakeDataModel", "RealDataModel"],
    "ins_name": ["Instance", "Name"],
    "ins_name_container": ["Instance", "NameContainer"],
    "ins_class_desc": ["Instance", "ClassDescriptor"],
    "ins_class_name": ["Instance", "ClassName"],
    "ins_parent": ["Instance", "Parent"],
    "ins_children_start": ["Instance", "ChildrenStart"],
    "ins_children_end": ["Instance", "ChildrenEnd"],
    "module_bytecode": ["ModuleScript", "ByteCode"],
    "local_bytecode": ["LocalScript", "ByteCode"],
    "bytecode_ptr": ["ByteCode", "Pointer"],
    "bytecode_size": ["ByteCode", "Size"],
    "value": ["Misc", "Value"],
    "string_length": ["Misc", "StringLength"],
}


class OffsetsError(Exception):
    pass


class VersionError(OffsetsError):
    pass


class JSONError(OffsetsError):
    pass


class CacheError(OffsetsError):
    pass


class Offsets:
    def __init__(self, data):
        required = {
            "fake_datamodel_ptr", "real_datamodel_ptr", "ins_name",
            "ins_name_container", "ins_class_desc", "ins_class_name",
            "ins_parent", "ins_children_start", "ins_children_end",
            "module_bytecode", "local_bytecode", "bytecode_ptr", "bytecode_size",
            "fflag_enable_load_module", "value", "string_length",
        }
        missing = required - set(data)
        if missing:
            raise CacheError(f"offset cache is missing fields: {sorted(missing)}")

        for name in required:
            value = data[name]
            if not isinstance(value, int) or value < 0:
                raise CacheError(f"invalid offset value for {name}")

        self.fake_datamodel_ptr = data["fake_datamodel_ptr"]
        self.real_datamodel_ptr = data["real_datamodel_ptr"]
        self.ins_name = data["ins_name"]
        self.ins_name_container = data["ins_name_container"]
        self.ins_class_desc = data["ins_class_desc"]
        self.ins_class_name = data["ins_class_name"]
        self.ins_parent = data["ins_parent"]
        self.ins_children_start = data["ins_children_start"]
        self.ins_children_end = data["ins_children_end"]
        self.module_bytecode = data["module_bytecode"]
        self.local_bytecode = data["local_bytecode"]
        self.bytecode_ptr = data["bytecode_ptr"]
        self.bytecode_size = data["bytecode_size"]
        self.fflag_enable_load_module = data["fflag_enable_load_module"]
        fps_offset = data.get("fflag_task_scheduler_target_fps")
        if fps_offset is not None and (not isinstance(fps_offset, int) or fps_offset < 0):
            raise CacheError("invalid offset value for fflag_task_scheduler_target_fps")
        self.fflag_task_scheduler_target_fps = fps_offset
        self.value = data["value"]
        self.string_length = data["string_length"]


def _write_cache_atomic(payload: dict) -> None:
    appdata.mkdir(parents=True, exist_ok=True)
    cache_path = appdata / "offset_cache.json"
    with NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=appdata,
        prefix=".offset_cache.",
        suffix=".tmp",
        delete=False,
    ) as tmp:
        tmp.write(json.dumps(payload, indent=2))
        tmp_path = Path(tmp.name)

    try:
        os.replace(tmp_path, cache_path)
    except OSError:
        try:
            tmp_path.unlink(missing_ok=True)
        finally:
            raise


def _fetch_json(session: requests.Session, url: str) -> dict:
    try:
        response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        raise OffsetsError(f"failed to fetch {url}: {exc}") from exc
    except ValueError as exc:
        raise JSONError(f"invalid JSON returned by {url}") from exc


def update(version: str) -> None:
    session = requests.Session()
    offsets_json = _fetch_json(session, f"{OFFSETS_BASE_URL}/{version}/offsets.json")
    fflags_json = _fetch_json(session, f"{OFFSETS_BASE_URL}/{version}/fflags.json")

    if "error" in offsets_json or "error" in fflags_json:
        api_error = offsets_json.get("error") or fflags_json.get("error")
        raise VersionError(f"offsets service has no data for {version}: {api_error}")

    try:
        offset_root = offsets_json["Offsets"]
        fflag_root = fflags_json["FFlagOffsets"]["FFlags"]

        cache_offsets = {
            "fflag_enable_load_module": int(fflag_root["EnableLoadModule"]),
        }

        if fflag_root.get("TaskSchedulerTargetFps") is not None:
            cache_offsets["fflag_task_scheduler_target_fps"] = int(
                fflag_root["TaskSchedulerTargetFps"]
            )

        for name, path in offsets_to_copy.items():
            value = offset_root
            for key in path:
                value = value[key]
            cache_offsets[name] = int(value)
    except (KeyError, TypeError, ValueError) as exc:
        raise JSONError(f"unexpected offset schema for {version}") from exc

    payload = {
        "schema": CACHE_SCHEMA,
        "roblox_version": version,
        "offsets": cache_offsets,
    }
    _write_cache_atomic(payload)


def check(version: str) -> None:
    cache_path = appdata / "offset_cache.json"
    needs_update = True

    if cache_path.exists():
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            needs_update = (
                payload.get("schema") != CACHE_SCHEMA
                or payload.get("roblox_version") != version
            )
            if not needs_update:
                Offsets(payload["offsets"])
        except (OSError, ValueError, KeyError, CacheError, TypeError):
            needs_update = True

    if needs_update:
        update(version)


def get() -> Offsets:
    cache_path = appdata / "offset_cache.json"
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        if payload.get("schema") != CACHE_SCHEMA:
            raise CacheError("unsupported offset cache schema")
        return Offsets(payload["offsets"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise CacheError("could not read offset cache") from exc
