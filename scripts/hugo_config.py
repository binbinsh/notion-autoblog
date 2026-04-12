import json
import subprocess
from typing import Any


def read_hugo_config(site_dir: str | None = None) -> dict[str, Any]:
    """Read the effective Hugo config via the Hugo CLI."""
    return _read_hugo_config_via_cli(site_dir)


def infer_languages_from_config(data: dict[str, Any]) -> list[str]:
    """Infer Hugo languages from an already loaded config dictionary."""
    return _infer_languages_from_hugo_dict(data)


def infer_languages_from_hugo(site_dir: str | None = None) -> list[str]:
    """Infer Hugo languages.

    - languages[0] is the default/source language
    - languages[1:] are translation targets
    """
    return infer_languages_from_config(read_hugo_config(site_dir))


def _source_language_override(data: dict[str, Any]) -> str:
    params = data.get("params") or data.get("Params") or {}
    if not isinstance(params, dict):
        return ""
    translate_params = params.get("translate") or params.get("Translate") or {}
    if not isinstance(translate_params, dict):
        return ""
    # Hugo CLI outputs JSON with lowercase keys (Viper behavior)
    value = translate_params.get("sourcelanguage")
    if not value:
        return ""
    return str(value).strip().lower()


def _read_hugo_config_via_cli(site_dir: str | None = None) -> dict[str, Any]:
    """Read effective Hugo config via `hugo config --format json`."""
    proc = subprocess.run(
        ["hugo", "config", "--format", "json"],
        capture_output=True,
        text=True,
        cwd=site_dir or None,
    )
    if proc.returncode != 0:
        location = f" in {site_dir}" if site_dir else ""
        raise RuntimeError(f"`hugo config --format json` failed{location}: {proc.stderr.strip()}")

    out = (proc.stdout or "").strip()
    if not out:
        raise RuntimeError("`hugo config --format json` returned empty output")

    parsed = json.loads(out)
    if not isinstance(parsed, dict):
        raise RuntimeError("`hugo config --format json` returned non-object JSON")
    return parsed


def _infer_languages_from_hugo_dict(data: dict[str, Any]) -> list[str]:
    # Hugo config output may vary in key casing (cli JSON vs file parsing).
    default_lang = (
        (data.get("defaultContentLanguage") or data.get("defaultcontentlanguage") or data.get("DefaultContentLanguage") or "")
    ).strip()
    override_lang = _source_language_override(data)

    languages = (
        data.get("languages")
        or data.get("Languages")
        or {}
    )
    if not isinstance(languages, dict):
        return []

    weights: dict[str, int] = {}
    codes: list[str] = []
    for code, meta in languages.items():
        code_l = str(code).strip().lower()
        if not code_l:
            continue
        if code_l not in codes:
            codes.append(code_l)
        if isinstance(meta, dict):
            w = meta.get("weight")
            if isinstance(w, int):
                weights[code_l] = w

    if not codes:
        if override_lang:
            return [override_lang]
        return [default_lang.lower()] if default_lang else []

    if default_lang:
        default_lang = default_lang.lower()
    else:
        # Best-effort: choose smallest weight when available, else first defined.
        default_lang = min(weights.items(), key=lambda kv: kv[1])[0] if weights else codes[0]

    if override_lang:
        default_lang = override_lang

    others = [c for c in codes if c != default_lang]
    if weights:
        others.sort(key=lambda c: (weights.get(c, 10**9), c))
    return [default_lang] + others
