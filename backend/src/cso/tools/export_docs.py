"""Facts for the generated pages of the docs site: `uv run python -m cso.tools.export_docs`.

The site (site/scripts/generate.mjs) runs this at build time and turns the JSON into the settings,
command line, roles and schema reference pages, so those pages cannot drift from the code. Nothing
here reads a secret: a secret setting is listed by name and marked, its value is never read.
"""

from __future__ import annotations

import argparse
import json
import sys
import typing
from pathlib import Path
from typing import Any

from pydantic import SecretStr
from pydantic.fields import FieldInfo
from pydantic_core import PydanticUndefined

from cso.api.inventory import INVENTORY
from cso.cli import build_parser
from cso.domain.config import CommunityConfig
from cso.domain.receipt import DecisionReceipt
from cso.settings import Settings

OPENAPI_PATH = Path(__file__).resolve().parents[3] / "openapi" / "v1.json"


def _type_text(annotation: Any) -> str:
    """A reader's name for a field type: `one of replay, live`, `text`, `number`, `yes or no`."""
    args = typing.get_args(annotation)
    origin = typing.get_origin(annotation)
    if origin is typing.Literal:
        return "one of " + ", ".join(str(a) for a in args)
    if origin is not None and type(None) in args:  # Optional[X]
        inner = [a for a in args if a is not type(None)]
        return _type_text(inner[0]) + ", optional" if inner else "optional"
    if annotation is bool:
        return "yes or no"
    if annotation is int:
        return "whole number"
    if annotation is float:
        return "number"
    if annotation is SecretStr:
        return "secret text"
    return "text"


def _default_text(field: FieldInfo) -> str:
    if field.default is PydanticUndefined:
        return "required"
    if field.default is None:
        return "not set"
    if isinstance(field.default, bool):
        return "true" if field.default else "false"
    if field.default == "":
        return "empty"
    return str(field.default)


def settings_facts() -> list[dict[str, Any]]:
    rows = []
    for name, field in Settings.model_fields.items():
        annotation = field.annotation
        rows.append(
            {
                "env": f"CSO_{name.upper()}",
                "type": _type_text(annotation),
                "default": _default_text(field),
                "secret": "SecretStr" in str(annotation),
                "description": field.description or "",
            }
        )
    return rows


def _argument_facts(action: argparse.Action) -> dict[str, Any]:
    return {
        "flags": list(action.option_strings),
        "name": action.dest if not action.option_strings else None,
        "help": action.help if isinstance(action.help, str) else "",
        "default": None if action.default in (None, argparse.SUPPRESS) else str(action.default),
        "choices": [str(c) for c in action.choices] if action.choices else [],
        "required": bool(action.required) if action.option_strings else True,
        "metavar": action.metavar if isinstance(action.metavar, str) else None,
    }


def _walk(parser: argparse.ArgumentParser, path: tuple[str, ...]) -> list[dict[str, Any]]:
    commands: list[dict[str, Any]] = []
    sub_actions = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]  # noqa: SLF001
    arguments = [
        _argument_facts(a)
        for a in parser._actions  # noqa: SLF001
        if not isinstance(a, argparse._SubParsersAction)  # noqa: SLF001
        and not isinstance(a, argparse._HelpAction)  # noqa: SLF001
    ]
    if path:
        commands.append(
            {
                "command": " ".join(path),
                "description": parser.description or "",
                "arguments": arguments,
                "subcommands": [name for action in sub_actions for name in action.choices],
            }
        )
    for action in sub_actions:
        helps = {choice.dest: choice.help for choice in action._choices_actions}  # noqa: SLF001
        for name, child in action.choices.items():
            if not child.description and helps.get(name):
                child.description = helps[name]
            commands.extend(_walk(child, (*path, name)))
    return commands


def cli_facts() -> list[dict[str, Any]]:
    return _walk(build_parser(), ("cso",))


def roles_facts() -> list[dict[str, Any]]:
    """One row per endpoint: the lowest role that can call it, from the contract inventory."""
    spec = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
    summaries: dict[tuple[str, str], str] = {}
    for path, item in spec.get("paths", {}).items():
        for method, operation in item.items():
            if isinstance(operation, dict):
                summaries[(method.upper(), path)] = str(
                    operation.get("summary") or operation.get("operationId") or ""
                )
    rows = []
    for endpoint in INVENTORY:
        key = (endpoint.method, endpoint.full_path)
        rows.append(
            {
                "method": endpoint.method,
                "path": endpoint.full_path,
                "role": endpoint.role.value if endpoint.role is not None else "no sign-in",
                "summary": summaries.get(key, ""),
                "errors": list(endpoint.errors),
            }
        )
    return rows


def build_facts() -> dict[str, Any]:
    return {
        "settings": settings_facts(),
        "cli": cli_facts(),
        "roles": roles_facts(),
        "schemas": {
            "community_pack": CommunityConfig.model_json_schema(),
            "receipt": DecisionReceipt.model_json_schema(),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--out", help="write the JSON here instead of standard output")
    args = parser.parse_args(argv)
    text = json.dumps(build_facts(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8", newline="\n")
    else:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
