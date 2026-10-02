"""Local message catalogue shared with the web UI. Never translate JSON keys or data."""

import json
import os
import re
from pathlib import Path

ENGLISH = json.loads(
    (Path(__file__).parent / "locales/en.json").read_text(encoding="utf-8")
)
_language = "zh-CN"


def resolve_language(preference=None, environ=None):
    env = os.environ if environ is None else environ
    selected = preference or env.get("EMMC_STUDIO_LANG", "auto")
    if selected in ("zh", "zh-CN"):
        return "zh-CN"
    if selected in ("en", "en-US"):
        return "en"
    # LC_ALL overrides category-specific locale, then LANG. C/POSIX use English.
    system = env.get("LC_ALL") or env.get("LC_MESSAGES") or env.get("LANG") or "C"
    return "zh-CN" if system.lower().startswith("zh") else "en"


def set_language(preference=None):
    global _language
    _language = resolve_language(preference)
    return _language


_patterns = []
for _source, _target in ENGLISH.items():
    if re.search(r"\{\d+\}", _source):
        _indexes = []
        _parts = []
        for _part in re.split(r"(\{\d+\})", _source):
            if re.fullmatch(r"\{\d+\}", _part):
                _indexes.append(int(_part[1:-1]))
                _parts.append("(.*?)")
            else:
                _parts.append(re.escape(_part))
        _patterns.append(
            (re.compile("^" + "".join(_parts) + "$", re.S), _target, _indexes)
        )


def t(message, values=()):
    if _language != "en":
        return re.sub(
            r"\{(\d+)\}",
            lambda m: str(values[int(m[1])]) if int(m[1]) < len(values) else m[0],
            message,
        )
    template = ENGLISH.get(message)
    if template is None:
        normalized = re.sub(r"\s+", " ", message).strip()
        template = ENGLISH.get(normalized)
        if template is not None:
            prefix = message[: len(message) - len(message.lstrip())]
            suffix = message[len(message.rstrip()) :]
            template = prefix + template + suffix
    if template is not None:
        return re.sub(
            r"\{(\d+)\}",
            lambda m: str(values[int(m[1])]) if int(m[1]) < len(values) else m[0],
            template,
        )
    for pattern, target, indexes in _patterns:
        match = pattern.fullmatch(message)
        if match:
            return re.sub(
                r"\{(\d+)\}", lambda m: match[indexes.index(int(m[1])) + 1], target
            )
    return message


def localize_status(value):
    """Localize known status fields for human output; machine JSON stays unchanged."""
    if isinstance(value, list):
        return [localize_status(item) for item in value]
    if isinstance(value, dict):
        return {
            key: (
                t(item)
                if key in {"phase", "error", "message", "note", "title"}
                and isinstance(item, str)
                else localize_status(item)
            )
            for key, item in value.items()
        }
    return value
