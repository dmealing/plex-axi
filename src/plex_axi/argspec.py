"""Command declarations, argument parsing and ``--help`` rendering.

Every command declares its own flags per subcommand. Anything undeclared is
rejected by name with the subcommand's valid flags printed inline, so an agent
that guessed wrong corrects itself in one turn rather than two.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .errors import UsageError
from .playback import ACCESS as PLAYBACK_ACCESS
from .writes import ACCESS as WRITE_ACCESS
from .writes import READ_ONLY

#: What every access level means, in one line. Each gate owns its own entry --
#: :mod:`plex_axi.writes` the two that describe what a command does to the
#: library, :mod:`plex_axi.playback` the one that describes what it does to a
#: speaker -- and they are merged here, where `--help` and the generated skill
#: both read them, rather than one module naming the other's variable.
ACCESS = {**WRITE_ACCESS, **PLAYBACK_ACCESS}

#: Flags accepted on every command, and therefore never reported as unknown.
GLOBAL_FLAGS = (
    "--help",
    "-h",
    "--human",
    "--json",
    "--timeout",
    "--section",
    "--user",
    "--debug",
    "--version",
    "-v",
    "-V",
)

#: The globals that consume the next token. Declared once so the parser, the
#: pre-scan and `--help` detection cannot disagree about where a value ends.
VALUE_GLOBALS = ("--timeout", "--section", "--user")

#: How each value-taking global is spelled back in a usage error.
_GLOBAL_EXAMPLE = {
    "--timeout": "plex-axi --timeout 60 <command>",
    "--section": "plex-axi --section 'Example Music' <command>",
    "--user": "plex-axi --user '<plex-username>' <command>",
}

#: Flags an agent might plausibly reach for, mapped to what actually exists.
#: A targeted hint beats the generic list when the intent is unambiguous.
RENAMED: dict = {
    # Video vocabulary, which is what every other Plex tool in the landscape is
    # shaped around. Pointing it at the music equivalent is more useful than the
    # generic list, because the agent's guess says exactly what it meant.
    "--title": "--track",
    "--name": "--track",
    "--song": "--track",
    "--band": "--artist",
    "--albumartist": "--artist",
    "--album-artist": "--artist",
    "--record": "--album",
    "--search": "--query",
    "--text": "--query",
    "--rating": "--rated-min",
    "--min-rating": "--rated-min",
    "--stars": "--rated-min",
    "--count": "--limit",
    "--max": "--limit",
    "--top": "--limit",
    "--kind": "--type",
    "--libtype": "--type",
    "--format": "--fields",
    "--output": "--fields",
    "--group": "--no-group",
    "--dedupe": "--no-group",
}


@dataclass(frozen=True)
class Flag:
    """One declared flag on one subcommand."""

    name: str
    metavar: str = ""
    repeat: bool = False
    default: Any = None
    boolean: bool = False
    note: str = ""

    @property
    def takes_value(self) -> bool:
        return not self.boolean

    def render(self) -> str:
        parts = [self.name]
        if self.metavar:
            parts.append(self.metavar)
        text = " ".join(parts)
        extras = []
        if self.repeat:
            extras.append("repeatable")
        if self.default not in (None, False):
            extras.append(f"default {self.default}")
        if self.note:
            extras.append(self.note)
        return f"{text} ({', '.join(extras)})" if extras else text


@dataclass(frozen=True)
class Sub:
    """One subcommand: its positional arguments and its flag set.

    ``access`` is empty when the subcommand sits on the same side of the
    read/write line as the rest of its command, which is the usual case. It is
    set only where one noun holds both, as ``playlist`` does.
    """

    name: str
    args: tuple = ()
    flags: tuple = ()
    summary: str = ""
    access: str = ""

    def signature(self) -> str:
        return " ".join([self.name, *self.args]) if self.args else self.name


@dataclass(frozen=True)
class Command:
    """A top-level command grouping subcommands under one noun.

    ``access`` defaults to read-only, and the default is what makes the
    declaration safe: a command added without anyone thinking about the question
    is described as the thing it almost certainly is, while a command that
    mutates has to say so before the gate in :mod:`plex_axi.writes` will run it.
    """

    name: str
    summary: str
    subs: tuple = ()
    examples: tuple = ()
    default_sub: str | None = None
    notes: tuple = ()
    usage: str = ""
    access: str = READ_ONLY

    def find(self, name: str) -> Sub | None:
        for sub in self.subs:
            if sub.name == name:
                return sub
        return None

    def access_for(self, sub: Sub) -> str:
        return sub.access or self.access

    def access_groups(self) -> list:
        """``(access, [subcommand names])`` in declaration order.

        One group is the ordinary case and renders as a single line. Two is
        ``playlist``, where listing is a read and adding is not, and one line
        for the whole noun would be wrong about half of it.
        """
        groups: list = []
        for sub in self.subs:
            level = self.access_for(sub)
            if groups and groups[-1][0] == level:
                groups[-1][1].append(sub.name)
            else:
                groups.append((level, [sub.name]))
        return groups


@dataclass
class Parsed:
    """The result of parsing one invocation."""

    positionals: list = field(default_factory=list)
    flags: dict = field(default_factory=dict)
    globals: dict = field(default_factory=dict)

    def get(self, name: str, default=None):
        return self.flags.get(_key(name), default)

    def has(self, name: str) -> bool:
        return _key(name) in self.flags


def _key(flag_name: str) -> str:
    return flag_name.lstrip("-").replace("-", "_")


def parse(sub: Sub, argv: list, *, command: Command) -> Parsed:
    """Parse ``argv`` against ``sub``'s declaration, rejecting anything undeclared."""
    declared = {flag.name: flag for flag in sub.flags}
    result = Parsed()
    for flag in sub.flags:
        if flag.repeat:
            result.flags[_key(flag.name)] = []
        elif flag.boolean:
            result.flags[_key(flag.name)] = False
        elif flag.default is not None:
            result.flags[_key(flag.name)] = flag.default

    index = 0
    while index < len(argv):
        token = argv[index]
        index += 1

        if token == "--":
            result.positionals.extend(argv[index:])
            break

        if not token.startswith("-") or token == "-":
            result.positionals.append(token)
            continue

        name, _, inline = token.partition("=")
        has_inline = bool(_)

        if name in GLOBAL_FLAGS:
            # Globals are accepted after the subcommand as well as before it.
            # They are recorded rather than rejected, and applied by the caller.
            if name in VALUE_GLOBALS:
                key = name.lstrip("-")
                if has_inline:
                    result.globals[key] = inline
                elif index < len(argv):
                    result.globals[key] = argv[index]
                    index += 1
                else:
                    raise UsageError(
                        f"{name} needs a value",
                        help_lines=[f"Run `{_GLOBAL_EXAMPLE[name]}`"],
                        code=f"BAD_{key.upper()}",
                    )
            else:
                result.globals[name.lstrip("-")] = True
            continue

        flag = declared.get(name)
        if flag is None:
            raise _unknown_flag(name, sub, command)

        if flag.boolean:
            if has_inline and inline.lower() in ("false", "0", "no"):
                result.flags[_key(name)] = False
            else:
                result.flags[_key(name)] = True
            continue

        if has_inline:
            value = inline
        else:
            if index >= len(argv):
                raise UsageError(
                    f"{name} needs a value",
                    help_lines=[
                        f"Run `{_invocation(command, sub)} {name} {flag.metavar or '<value>'}`"
                    ],
                    code="MISSING_VALUE",
                )
            value = argv[index]
            index += 1

        if flag.repeat:
            result.flags[_key(name)].append(value)
        else:
            result.flags[_key(name)] = value

    _check_positionals(sub, command, result.positionals)
    return result


def _label(command: Command, sub: Sub) -> str:
    """How one subcommand is named in a message.

    Most nouns here have a single subcommand named after the noun itself, so
    spelling both would render `search search` -- which is not a command anyone
    can run, and an agent copying it would fail twice.
    """
    if sub.name == command.name or (sub.name == command.default_sub and len(command.subs) == 1):
        return command.name
    return f"{command.name} {sub.name}"


def _invocation(command: Command, sub: Sub) -> str:
    return f"plex-axi {_label(command, sub)}"


def _usage(command: Command, sub: Sub) -> str:
    """The runnable form of one subcommand, with no trailing space.

    A subcommand that takes no positional arguments used to render as
    ``Run `plex-axi playlist list ` `` -- a command line with a space inside the
    backticks, which reads as an argument the author forgot to name.
    """
    return " ".join([_invocation(command, sub), *sub.args]).rstrip()


def _check_positionals(sub: Sub, command: Command, values: list) -> None:
    required = [a for a in sub.args if a.startswith("<")]
    if len(values) < len(required):
        missing = required[len(values)]
        raise UsageError(
            f"{_invocation(command, sub)} needs {missing}",
            help_lines=[f"Run `{_usage(command, sub)}`"],
            code="MISSING_ARGUMENT",
        )
    if len(values) > len(sub.args):
        extra = values[len(sub.args)]
        raise UsageError(
            f"unexpected argument {extra!r} for `{_label(command, sub)}`",
            help_lines=[f"Run `{_usage(command, sub)}`"],
            code="UNEXPECTED_ARGUMENT",
        )


def _unknown_flag(name: str, sub: Sub, command: Command):
    replacement = RENAMED.get(name)
    valid = [flag.name for flag in sub.flags]
    if replacement and replacement in valid:
        return UsageError(
            f"unknown flag {name} for `{_label(command, sub)}`; use {replacement} instead",
            help_lines=[f"Run `{_invocation(command, sub)} {replacement} <value>`"],
            code="UNKNOWN_FLAG",
        )
    listing = ", ".join(valid) if valid else "(none)"
    return UsageError(
        f"unknown flag {name} for `{_label(command, sub)}`",
        help_lines=[
            f"valid flags for `{_label(command, sub)}`: {listing} (--help always allowed)",
            f"Run `plex-axi {command.name} --help` for the full reference",
        ],
        code="UNKNOWN_FLAG",
    )


# --------------------------------------------------------------------- help


def render_access(command: Command) -> list:
    """The ``access:`` block: whether this command reads or writes, in one line.

    Printed immediately under the description rather than among the notes,
    because "can this change my library?" is not a footnote, and an agent that
    has to read to the bottom of the help to find out will not.
    """
    groups = command.access_groups()
    if len(groups) < 2:
        level = groups[0][0] if groups else command.access
        return ["access:", f"  {ACCESS[level]}"]
    lines = [f"access[{len(groups)}]:"]
    lines.extend(f"  {', '.join(names)}: {ACCESS[level]}" for level, names in groups)
    return lines


def render_command_help(command: Command) -> str:
    """Render one command's concise, complete reference."""
    lines = [command.usage or f"usage: plex-axi {command.name} <subcommand> [flags]"]
    lines.append(f"description: {command.summary}")
    lines.extend(render_access(command))

    if command.subs and not (len(command.subs) == 1 and command.subs[0].name == command.name):
        signatures = [sub.signature() for sub in command.subs]
        lines.append(f"subcommands[{len(signatures)}]:")
        lines.append("  " + ", ".join(signatures))

    for sub in command.subs:
        label = sub.name
        rendered = [flag.render() for flag in sub.flags]
        lines.append(f"flags{{{label}}}:")
        lines.append("  " + (", ".join(rendered) if rendered else "(none)"))

    for note in command.notes:
        lines.append("note:")
        lines.append(f"  {note}")

    if command.examples:
        lines.append("examples:")
        lines.extend(f"  {example}" for example in command.examples)
    return "\n".join(lines)
