"""Read the loaded model into plain values, and refuse one that does not hold together.

The loader has already checked what it can: an ``extends`` naming an attribute that
does not exist, or one of another type, never gets this far. What it cannot check is
inside the property bags, which carry no registered vocabulary, so those are checked
here and a model that fails raises :class:`ModelError` before anything is written.
"""

from __future__ import annotations

from dataclasses import dataclass


class ModelError(ValueError):
    """The model loads, and still says something the generators cannot honour."""


@dataclass(frozen=True)
class Upstream:
    """One object the server answers: its attributes and the captures that show them."""

    fqn: str
    key: str
    element: str
    capture: tuple
    fields: tuple
    required: tuple
    unobserved: dict


@dataclass(frozen=True)
class Row:
    """One row the tool prints: its columns, its default set and what each column reads."""

    fqn: str
    key: str
    of: str
    capture: tuple
    reads: dict
    default: tuple


def bag(node, name):
    """A property bag, read through the resolving accessor so an inherited one is seen."""
    value = node.attrs().get(name)
    return getattr(value, "value", value)


def fqn(obj) -> str:
    package = getattr(obj, "package", None) or getattr(obj, "file_default_package", None)
    return f"{package}::{obj.name}" if package else obj.name


def _objects(root) -> list:
    return [child for child in root.children() if getattr(child, "type", "") == "object"]


def _extends(field):
    """The member a field extends, as ``(owner, member)``, or ``None``."""
    ref = getattr(field, "super_ref", None)
    if not ref or "." not in str(ref):
        return None
    owner, member = str(ref).rsplit(".", 1)
    return owner, member


def _names(value, what: str) -> tuple:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ModelError(f"{what} must be a list of names")
    return tuple(value)


def capture_file(root) -> str:
    """The committed capture, as a path from the project root."""
    settings = bag(root, "capture")
    if not isinstance(settings, dict) or not isinstance(settings.get("file"), str):
        raise ModelError("the model root needs a `capture` bag naming its `file`")
    return settings["file"]


def upstream(root) -> list:
    found = []
    for obj in _objects(root):
        wire = bag(obj, "wire")
        if wire is None:
            continue
        name = fqn(obj)
        for needed in ("key", "element", "capture"):
            if needed not in wire:
                raise ModelError(f"{name}: the `wire` bag needs `{needed}`")
        fields = obj.fields()
        unobserved = {}
        for field in fields:
            excuse = bag(field, "unobserved")
            if excuse is None:
                continue
            reason = excuse.get("reason") if isinstance(excuse, dict) else None
            if not isinstance(reason, str) or not reason.strip():
                raise ModelError(f"{name}.{field.name}: `unobserved` needs a `reason`")
            unobserved[field.name] = reason
        found.append(
            Upstream(
                fqn=name,
                key=wire["key"],
                element=wire["element"],
                capture=_names(wire["capture"], f"{name}: `wire.capture`"),
                fields=tuple(field.name for field in fields),
                required=tuple(f.name for f in fields if f.attrs().get("required")),
                unobserved=unobserved,
            )
        )
    keys = [entry.key for entry in found]
    if len(set(keys)) != len(keys):
        raise ModelError(f"two objects share a `wire.key`: {sorted(keys)}")
    return found


def _defaults(root) -> dict:
    """Each projection that is a subset of one object's fields, by that object."""
    found: dict = {}
    for obj in _objects(root):
        if obj.sub_type != "projection":
            continue
        refs = [_extends(field) for field in obj.fields()]
        owners = {ref[0] for ref in refs if ref}
        if not all(refs) or len(owners) != 1:
            continue
        owner = owners.pop()
        if owner in found:
            raise ModelError(f"{owner} has two default projections")
        found[owner] = tuple(field.name for field in obj.fields())
    return found


def rows(root) -> list:
    sources = {entry.fqn: entry for entry in upstream(root)}
    defaults = _defaults(root)
    found = []
    for obj in _objects(root):
        row = bag(obj, "row")
        if row is None:
            continue
        name = fqn(obj)
        for needed in ("key", "of", "capture"):
            if needed not in row:
                raise ModelError(f"{name}: the `row` bag needs `{needed}`")
        source = sources.get(row["of"])
        if source is None:
            raise ModelError(f"{name}: `row.of` names {row['of']!r}, which declares no `wire`")
        capture = _names(row["capture"], f"{name}: `row.capture`")
        stray = sorted(set(capture) - set(source.capture))
        if stray:
            raise ModelError(f"{name}: `row.capture` names {stray}, not answers of {source.fqn}")
        reads = {}
        for field in obj.fields():
            column = f"{name}.{field.name}"
            ref = _extends(field)
            derived = bag(field, "derived")
            if ref and ref[0] == source.fqn:
                reads[field.name] = (ref[1],)
                continue
            if not isinstance(derived, dict) or not derived.get("reads"):
                raise ModelError(
                    f"{column} says nothing about where it is read from: extend an "
                    f"attribute of {source.fqn}, or name what it reads in a `derived` bag"
                )
            names = _names(derived["reads"], f"{column}: `derived.reads`")
            unknown = sorted(set(names) - set(source.fields))
            if unknown:
                raise ModelError(f"{column} reads {unknown}, which {source.fqn} does not declare")
            reads[field.name] = names
        if name not in defaults:
            raise ModelError(f"{name} has no default projection")
        found.append(
            Row(
                fqn=name,
                key=row["key"],
                of=source.fqn,
                capture=capture,
                reads=reads,
                default=defaults[name],
            )
        )
    keys = [entry.key for entry in found]
    if len(set(keys)) != len(keys):
        raise ModelError(f"two rows share a `row.key`: {sorted(keys)}")
    return found
