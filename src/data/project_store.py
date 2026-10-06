"""Portable project, session, and preset storage for ELUTEC.

Project manifests are the source of truth for project metadata. Large artifacts
stay as ordinary files beside each session manifest; paths recorded in manifests
are relative so a project can be moved as one folder.
"""
from __future__ import annotations

import copy
import json
import os
import re
import shutil
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ..config import DEFAULT_DETECTOR_PRESETS, PERFORMANCE_PROFILES

PROJECT_FILENAME = "project.json"
PROJECT_FORMAT = "elutec-project"
PROJECT_SCHEMA_VERSION = 1
SESSION_SCHEMA_VERSION = 1
PRESET_SCHEMA_VERSION = 1
PRESET_KINDS = ("analysis", "detector", "graphs", "markers")


def _now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _slug(value, fallback="analysis"):
    value = str(value or "").strip()
    value = re.sub(r"[^\w.-]+", "-", value, flags=re.UNICODE).strip(" .-_")
    return value[:64] or fallback


def _canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _atomic_write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _read_json(path, fallback=None):
    try:
        with open(path, "r", encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, ValueError, TypeError):
        return copy.deepcopy(fallback)


def _safe_source(source):
    """Keep useful source metadata without persisting URL credentials."""
    value = str(source or "").strip()
    if not value:
        return ""
    try:
        parsed = urlsplit(value)
        if parsed.scheme and parsed.hostname:
            host = parsed.hostname
            if ":" in host and not host.startswith("["):
                host = f"[{host}]"
            try:
                if parsed.port:
                    host = f"{host}:{parsed.port}"
            except ValueError:
                pass
            netloc = f"***@{host}" if parsed.username or parsed.password else host
            secret_tokens = ("password", "passwd", "token", "secret", "key", "auth")
            query = urlencode([
                (key, "***" if any(token in key.lower() for token in secret_tokens) else item)
                for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            ])
            # Fragments are not needed to reconnect and can carry access tokens.
            return urlunsplit((parsed.scheme, netloc, parsed.path, query, ""))
    except Exception:
        pass
    # Malformed camera URLs should still not leak user-info in the fallback.
    return re.sub(r"(?<=//)[^/@]+@", "***@", value)


def _safe_text(value):
    """Mask credentials in URL fragments embedded in exception/log text."""
    text = str(value or "")
    url_pattern = re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s\"'<>]+")
    return url_pattern.sub(lambda match: _safe_source(match.group(0)), text)


def _json_safe(value):
    """Convert configuration data into JSON-compatible values, omitting secrets."""
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            key_text = str(key)
            if any(token in key_text.lower() for token in (
                "password", "passwd", "token", "secret", "api_key", "access_key",
                "license", "credential", "activation_key",
            )):
                continue
            safe = _json_safe(item)
            if safe is not _OMIT:
                out[key_text] = safe
        return out
    if isinstance(value, (list, tuple)):
        return [safe for item in value if (safe := _json_safe(item)) is not _OMIT]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return _OMIT


class _Omit:
    pass


_OMIT = _Omit()


def _builtin_presets():
    balanced = dict(PERFORMANCE_PROFILES.get("Сбалансированный", {}))
    analysis = {
        "performance_profile": "Сбалансированный",
        **balanced,
        "roi_x": 300,
        "roi_y": 150,
        "roi_w": 200,
        "roi_h": 200,
        "roi_shape": "circle",
        "show_r": True,
        "show_g": True,
        "show_b": True,
        "show_log": True,
        "show_slope": True,
        "show_transition": True,
        "record_video": True,
        "save_roi_on_video": False,
        "live_roi": True,
        "allow_roi_resize": True,
        "auto_stop_file": True,
        "custom_variables": [],
        "custom_graphs": [],
        "custom_auto_marks": [],
    }
    graphs = {
        "show_r": True,
        "show_g": True,
        "show_b": True,
        "show_log": True,
        "show_slope": True,
        "show_transition": True,
        "custom_variables": [],
        "custom_graphs": [],
    }
    markers = {
        "auto_marks_enabled": True,
        "sound_alerts_enabled": True,
        "notifications_enabled": True,
        "custom_auto_marks": [],
    }
    return {
        "analysis": [{
            "id": "builtin:analysis.default",
            "kind": "analysis",
            "name": "Сбалансированный (Default)",
            "origin": "builtin",
            "version": 1,
            "locked": True,
            "settings": analysis,
        }],
        "detector": [{
            "id": "builtin:detector.default",
            "kind": "detector",
            "name": "По умолчанию (Default)",
            "origin": "builtin",
            "version": 1,
            "locked": True,
            "settings": copy.deepcopy(DEFAULT_DETECTOR_PRESETS.get("По умолчанию (Default)", {})),
        }],
        "graphs": [{
            "id": "builtin:graphs.default",
            "kind": "graphs",
            "name": "Стандартные графики (Default)",
            "origin": "builtin",
            "version": 1,
            "locked": True,
            "settings": graphs,
        }],
        "markers": [{
            "id": "builtin:markers.default",
            "kind": "markers",
            "name": "Стандартные автометки (Default)",
            "origin": "builtin",
            "version": 1,
            "locked": True,
            "settings": markers,
        }],
    }


BUILTIN_PRESETS = _builtin_presets()
BUILTIN_BY_ID = {
    record["id"]: record
    for records in BUILTIN_PRESETS.values()
    for record in records
}


class ProjectStore:
    """Manage one active project plus the user's global preset library."""

    def __init__(self, project_path=None):
        self.root = Path(project_path).expanduser().resolve() if project_path else None
        self.manifest_path = self.root / PROJECT_FILENAME if self.root else None
        self.manifest = None
        if self.root:
            manifest = _read_json(self.manifest_path)
            if not isinstance(manifest, dict) or manifest.get("format") != PROJECT_FORMAT:
                raise ValueError(f"Не найден корректный проект ELUTEC: {self.manifest_path}")
            self.manifest = manifest

    @staticmethod
    def app_data_root():
        return Path(os.path.expanduser("~")) / ".elutek"

    @classmethod
    def default_workspace_root(cls):
        settings = _read_json(cls.app_data_root() / "project-settings.json", {})
        configured = settings.get("workspace_root") if isinstance(settings, dict) else None
        if configured:
            return Path(configured).expanduser()
        home = Path(os.path.expanduser("~"))
        documents = home / "Documents"
        base = documents if documents.is_dir() else home
        return base / "Elutec Projects"

    @classmethod
    def set_default_workspace_root(cls, path):
        if not str(path or "").strip():
            raise ValueError("Выберите папку для проектов.")
        root = Path(path).expanduser()
        root.mkdir(parents=True, exist_ok=True)
        settings_path = cls.app_data_root() / "project-settings.json"
        settings = _read_json(settings_path, {})
        if not isinstance(settings, dict):
            settings = {}
        settings["workspace_root"] = str(root.resolve())
        _atomic_write_json(settings_path, settings)
        return root.resolve()

    @classmethod
    def create_project(cls, name, workspace_root=None, description=""):
        name = str(name or "").strip()
        if not name:
            raise ValueError("Укажите название проекта.")
        parent = Path(workspace_root).expanduser() if workspace_root else cls.default_workspace_root()
        parent.mkdir(parents=True, exist_ok=True)
        project_id = str(uuid.uuid4())
        folder = parent / f"{_slug(name, 'project')}_{project_id[:8]}"
        folder.mkdir(parents=False, exist_ok=False)
        for relative in (
            "presets/analysis", "presets/detector", "presets/graphs", "presets/markers",
            "media/sources", "sessions",
        ):
            (folder / relative).mkdir(parents=True, exist_ok=True)
        now = _now()
        global_store = cls()
        manifest = {
            "format": PROJECT_FORMAT,
            "schema_version": PROJECT_SCHEMA_VERSION,
            "project_id": project_id,
            "name": name,
            "description": str(description or "").strip(),
            "created_at": now,
            "updated_at": now,
            "default_presets": {kind: global_store.get_default_preset_id(kind) for kind in PRESET_KINDS},
        }
        _atomic_write_json(folder / PROJECT_FILENAME, manifest)
        store = cls(folder)
        store.touch_recent()
        return store

    @classmethod
    def open_project(cls, path):
        store = cls(path)
        store.touch_recent()
        return store

    @classmethod
    def recent_projects(cls):
        path = cls.app_data_root() / "recent-projects.json"
        payload = _read_json(path, {"projects": []})
        rows = payload.get("projects", []) if isinstance(payload, dict) else []
        valid = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            project_path = Path(str(row.get("path", ""))).expanduser()
            manifest = _read_json(project_path / PROJECT_FILENAME)
            if isinstance(manifest, dict) and manifest.get("format") == PROJECT_FORMAT:
                valid.append({
                    "path": str(project_path.resolve()),
                    "project_id": manifest.get("project_id", ""),
                    "name": manifest.get("name", project_path.name),
                    "last_opened": row.get("last_opened", ""),
                })
        return valid

    def touch_recent(self):
        if not self.root or not self.manifest:
            return
        path = self.app_data_root() / "recent-projects.json"
        payload = _read_json(path, {"projects": []})
        rows = payload.get("projects", []) if isinstance(payload, dict) else []
        current_path = str(self.root)
        kept = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                prior_path = str(Path(row.get("path", "")).expanduser().resolve())
            except (TypeError, OSError, ValueError):
                continue
            if prior_path != current_path:
                kept.append(row)
        kept.insert(0, {"path": current_path, "last_opened": _now()})
        try:
            _atomic_write_json(path, {"schema_version": 1, "projects": kept[:20]})
        except OSError as exc:
            # Recent-project bookkeeping must not make an otherwise valid
            # project impossible to create or open (e.g. read-only home dir).
            print(f"⚠️ Не удалось обновить список недавних проектов: {exc}")

    def update_project(self, **fields):
        if not self.manifest:
            raise RuntimeError("Сначала откройте проект.")
        allowed = {"name", "description", "default_presets", "metadata"}
        for key, value in fields.items():
            if key in allowed:
                self.manifest[key] = value
        self.manifest["updated_at"] = _now()
        _atomic_write_json(self.manifest_path, self.manifest)

    def set_default_preset(self, kind, preset_id):
        if kind not in PRESET_KINDS:
            raise ValueError(f"Неизвестная категория пресета: {kind}")
        if not self.get_preset(preset_id, kind):
            raise ValueError("Нельзя назначить пресет по умолчанию: пресет не найден.")
        if self.manifest:
            defaults = dict(self.manifest.get("default_presets", {}))
            defaults[kind] = str(preset_id)
            self.update_project(default_presets=defaults)
            return
        defaults_path = self.app_data_root() / "preset-defaults.json"
        defaults = _read_json(defaults_path, {})
        defaults[kind] = str(preset_id)
        _atomic_write_json(defaults_path, defaults)

    def get_default_preset_id(self, kind):
        if kind not in PRESET_KINDS:
            raise ValueError(f"Неизвестная категория пресета: {kind}")
        if self.manifest:
            value = self.manifest.get("default_presets", {}).get(kind)
            if value and self.get_preset(value, kind):
                return value
        defaults = _read_json(self.app_data_root() / "preset-defaults.json", {})
        value = defaults.get(kind) if isinstance(defaults, dict) else None
        if value and self.get_preset(value, kind):
            return value
        return f"builtin:{kind}.default"

    def _preset_dirs(self, kind):
        global_dir = self.app_data_root() / "presets" / kind
        if self.root:
            return [("user", global_dir), ("project", self.root / "presets" / kind)]
        return [("user", global_dir)]

    def list_presets(self, kind):
        if kind not in PRESET_KINDS:
            raise ValueError(f"Неизвестная категория пресета: {kind}")
        records = [copy.deepcopy(record) for record in BUILTIN_PRESETS[kind]]
        for origin, directory in self._preset_dirs(kind):
            if not directory.is_dir():
                continue
            for file in sorted(directory.glob("*.json"), key=lambda p: p.name.casefold()):
                record = _read_json(file)
                if not isinstance(record, dict) or record.get("kind") != kind:
                    continue
                record["origin"] = origin
                record["locked"] = False
                record["_file"] = str(file)
                records.append(record)
        return records

    def get_preset(self, preset_id, kind=None):
        preset_id = str(preset_id or "")
        builtin = BUILTIN_BY_ID.get(preset_id)
        if builtin and (kind is None or builtin.get("kind") == kind):
            return copy.deepcopy(builtin)
        if kind is None:
            for candidate_kind in PRESET_KINDS:
                match = self.get_preset(preset_id, candidate_kind)
                if match:
                    return match
            return None
        for record in self.list_presets(kind):
            if record.get("id") == preset_id:
                return record
        return None

    def save_preset(self, kind, name, settings, scope=None, based_on=None):
        if kind not in PRESET_KINDS:
            raise ValueError(f"Неизвестная категория пресета: {kind}")
        name = str(name or "").strip()
        if not name:
            raise ValueError("Укажите название пресета.")
        reserved = {item["name"].casefold() for item in BUILTIN_PRESETS[kind]}
        if name.casefold() in reserved:
            raise ValueError("Это имя зарезервировано встроенным пресетом. Используйте «Сохранить копию» с другим названием.")
        scope = scope or ("project" if self.root else "user")
        if scope == "project" and not self.root:
            raise ValueError("Для проектного пресета сначала откройте проект.")
        if scope not in ("project", "user"):
            raise ValueError("Область пресета должна быть project или user.")
        if any(r.get("name", "").casefold() == name.casefold() and r.get("origin") == scope for r in self.list_presets(kind)):
            raise ValueError(f"В этой области уже есть пресет «{name}».")
        preset_id = f"{scope}:{kind}:{uuid.uuid4()}"
        directory = (self.root / "presets" / kind) if scope == "project" else (self.app_data_root() / "presets" / kind)
        record = {
            "schema_version": PRESET_SCHEMA_VERSION,
            "id": preset_id,
            "kind": kind,
            "name": name,
            "origin": scope,
            "locked": False,
            "based_on": based_on,
            "created_at": _now(),
            "settings": _json_safe(settings),
        }
        _atomic_write_json(directory / f"{preset_id.rsplit(':', 1)[-1]}.json", record)
        if self.manifest:
            self.manifest["updated_at"] = _now()
            _atomic_write_json(self.manifest_path, self.manifest)
        return record

    def delete_preset(self, preset_id):
        preset = self.get_preset(preset_id)
        if not preset:
            raise ValueError("Пресет не найден.")
        if preset.get("locked") or str(preset_id).startswith("builtin:"):
            raise PermissionError("Встроенные пресеты нельзя изменить или удалить.")
        file_path = preset.get("_file")
        if not file_path:
            raise PermissionError("Не удалось определить расположение пресета.")
        Path(file_path).unlink()
        kind = preset.get("kind")
        if self.manifest and self.manifest.get("default_presets", {}).get(kind) == preset_id:
            defaults = dict(self.manifest.get("default_presets", {}))
            defaults[kind] = f"builtin:{kind}.default"
            self.update_project(default_presets=defaults)
        elif not self.manifest:
            defaults_path = self.app_data_root() / "preset-defaults.json"
            defaults = _read_json(defaults_path, {})
            if isinstance(defaults, dict) and defaults.get(kind) == preset_id:
                defaults[kind] = f"builtin:{kind}.default"
                _atomic_write_json(defaults_path, defaults)
        return preset

    def migrate_legacy_detector_presets(self, settings):
        """Move old mutable config.json detector presets into the user library.

        A modified legacy Default is preserved as a user copy; the packaged
        Default remains canonical and immutable.
        """
        legacy = settings.get("detector_presets") if isinstance(settings, dict) else None
        if not isinstance(legacy, dict):
            return False
        builtin = BUILTIN_PRESETS["detector"][0]
        canonical = builtin["settings"]
        existing = self.list_presets("detector")
        for old_name, old_settings in legacy.items():
            if not isinstance(old_settings, dict):
                continue
            name = str(old_name).strip()
            if not name:
                continue
            if name.casefold() == builtin["name"].casefold():
                if _canonical_json(old_settings) == _canonical_json(canonical):
                    continue
                name = "Default — пользовательская копия"
            if any(r.get("origin") == "user" and r.get("name", "").casefold() == name.casefold()
                   and _canonical_json(r.get("settings", {})) == _canonical_json(old_settings) for r in existing):
                continue
            existing_names = {r.get("name", "").casefold() for r in existing if r.get("origin") == "user"}
            base_name = name
            suffix = 2
            while name.casefold() in existing_names or name.casefold() in {builtin["name"].casefold()}:
                name = f"{base_name} ({suffix})"
                suffix += 1
            record = self.save_preset("detector", name, old_settings, scope="user")
            existing.append(record)
        settings.pop("detector_presets", None)
        return True

    def create_session(self, settings, source="", display_name="", sample_id=""):
        if not self.root or not self.manifest:
            raise RuntimeError("Перед запуском анализа выберите или создайте проект.")
        now = datetime.now().astimezone()
        session_id = f"{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        label = _slug(display_name or sample_id or "analysis", "analysis")
        session_dir = self.root / "sessions" / f"{session_id}__{label}"
        session_dir.mkdir(parents=True, exist_ok=False)
        (session_dir / "exports").mkdir()
        (session_dir / "logs").mkdir()

        source_value = str(source or "").strip()
        is_file = bool(source_value and (Path(source_value).expanduser().is_file()))
        source_record = {
            "kind": "file" if is_file else ("network" if "://" in source_value else "device"),
            "value": _safe_source(source_value),
            "original_path": source_value if is_file else None,
        }
        if is_file:
            try:
                source_path = Path(source_value).expanduser().resolve()
                source_record["portable"] = source_path.is_relative_to(self.root)
                if source_record["portable"]:
                    source_record["relative_path"] = source_path.relative_to(self.root).as_posix()
                    source_record["original_path"] = None
                else:
                    source_record["portable"] = False
            except (OSError, ValueError, AttributeError):
                source_record["portable"] = False

        settings = settings if isinstance(settings, dict) else {}
        snapshot = _json_safe(settings)
        for key in (
            "save_folder", "video_folder", "active_project_path", "project_id",
            "detector_presets", "session_path", "session_id", "exports_folder",
        ):
            snapshot.pop(key, None)
        snapshot.pop("source", None)
        preset_refs = copy.deepcopy(self.manifest.get("default_presets", {}))
        for kind in PRESET_KINDS:
            ref = preset_refs.get(kind)
            if not ref or not self.get_preset(ref, kind):
                preset_refs[kind] = f"builtin:{kind}.default"
        active_detector = settings.get("active_detector_preset_id")
        if active_detector and self.get_preset(active_detector, "detector"):
            preset_refs["detector"] = active_detector
        manifest = {
            "schema_version": SESSION_SCHEMA_VERSION,
            "session_id": session_id,
            "project_id": self.manifest["project_id"],
            "project_name": self.manifest.get("name", ""),
            "display_name": str(display_name or sample_id or "Анализ").strip(),
            "sample_id": str(sample_id or "").strip(),
            "status": "running",
            "created_at": _now(),
            "started_at": _now(),
            "ended_at": None,
            "source": source_record,
            "preset_refs": preset_refs,
            "settings_snapshot": snapshot,
            "artifacts": {},
        }
        try:
            _atomic_write_json(session_dir / "session.json", manifest)
        except Exception:
            shutil.rmtree(session_dir, ignore_errors=True)
            raise
        return {"id": session_id, "path": str(session_dir), "manifest": manifest}

    def finish_session(self, session_path, status, artifacts=None, error=None, extra=None):
        session_dir = Path(session_path).expanduser().resolve()
        manifest_path = session_dir / "session.json"
        manifest = _read_json(manifest_path)
        if not isinstance(manifest, dict):
            raise ValueError(f"Не найден манифест сессии: {manifest_path}")
        manifest["status"] = str(status)
        manifest["ended_at"] = _now()
        mapped = {}
        for key, value in (artifacts or {}).items():
            if not value:
                continue
            try:
                path = Path(value).expanduser().resolve()
                if path.exists():
                    mapped[key] = path.relative_to(session_dir).as_posix() if path.is_relative_to(session_dir) else str(path)
            except (OSError, ValueError, TypeError, AttributeError):
                continue
        manifest["artifacts"] = mapped
        if error:
            manifest["error"] = _safe_text(error)
        if extra:
            manifest.update(_json_safe(extra))
        _atomic_write_json(manifest_path, manifest)
        if self.manifest:
            self.manifest["updated_at"] = _now()
            _atomic_write_json(self.manifest_path, self.manifest)
        return manifest

    def list_sessions(self):
        if not self.root:
            return []
        rows = []
        sessions_root = self.root / "sessions"
        if not sessions_root.is_dir():
            return rows
        for folder in sessions_root.iterdir():
            if not folder.is_dir():
                continue
            manifest = _read_json(folder / "session.json")
            if isinstance(manifest, dict):
                manifest["path"] = str(folder)
                rows.append(manifest)
        return sorted(rows, key=lambda row: row.get("started_at", ""), reverse=True)

    @classmethod
    def import_legacy_folder(cls, source_folder, name, workspace_root=None):
        source = Path(source_folder).expanduser().resolve()
        if not source.is_dir():
            raise ValueError("Выберите существующую папку с результатами.")
        store = cls.create_project(name, workspace_root=workspace_root,
                                   description=f"Импорт из {source.name}")
        groups = {}
        unmatched = []
        for file in source.iterdir():
            if not file.is_file():
                continue
            stem = file.stem
            lower = file.name.lower()
            base = None
            role = None
            if lower.startswith("analysis_") and lower.endswith(".xlsx"):
                base, role = stem, "analysis"
            elif lower.startswith("analysis_") and lower.endswith("_raw_rgb.csv"):
                base, role = stem[:-8], "raw_csv"
            elif lower.startswith("analysis_") and lower.endswith("_video.mkv"):
                base, role = stem[:-6], "video"
            if base and role:
                groups.setdefault(base, {})[role] = file
            else:
                unmatched.append(file)

        for base, files in groups.items():
            suffix = uuid.uuid4().hex[:6]
            session_id = f"legacy_{_slug(base, 'analysis')}_{suffix}"
            session_dir = store.root / "sessions" / session_id
            (session_dir / "exports").mkdir(parents=True, exist_ok=True)
            (session_dir / "logs").mkdir(parents=True, exist_ok=True)
            artifacts = {}
            for role, file in files.items():
                target_name = {"analysis": "analysis.xlsx", "raw_csv": "raw_rgb.csv", "video": "capture.mkv"}[role]
                target = session_dir / target_name
                shutil.copy2(file, target)
                artifacts[role] = target.name
            manifest = {
                "schema_version": SESSION_SCHEMA_VERSION,
                "session_id": session_id,
                "project_id": store.manifest["project_id"],
                "project_name": store.manifest["name"],
                "display_name": base,
                "sample_id": "",
                "status": "imported",
                "created_at": _now(),
                "started_at": None,
                "ended_at": None,
                "source": {"kind": "legacy-import", "folder": str(source)},
                "preset_refs": {},
                "settings_snapshot": {},
                "artifacts": artifacts,
                "legacy_base_name": base,
            }
            _atomic_write_json(session_dir / "session.json", manifest)

        if unmatched:
            import_dir = store.root / "legacy_imports"
            import_dir.mkdir(parents=True, exist_ok=True)
            for file in unmatched:
                shutil.copy2(file, import_dir / file.name)
        store.update_project(metadata={"legacy_source_folder": str(source),
                                       "imported_sessions": len(groups),
                                       "unmatched_files": len(unmatched)})
        return store, {"sessions": len(groups), "unmatched": len(unmatched)}
