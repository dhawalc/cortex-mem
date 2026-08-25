"""Find policy inputs a benchmark harness can never exercise.

A decision function declares its inputs as the fields of a frozen value object.
A benchmark harness populates some subset of those fields on every write it
makes. Any declared input outside that subset is *unfalsifiable by that
benchmark*: no run over that corpus, green or red, carries information about
the branches predicated on it. A green result there is not weak evidence. It
is zero evidence.

That intersection is computable without a model and without a network:

    declared  = fields the decision function reads, by AST of its own source
    covered   = fields the harness ever populates, by trace of one run
    blindspot = declared - covered

``blindspot`` computes it, prints the coverage table, and exits non-zero when
a read input has zero coverage.

Two properties worth stating precisely, because they bound what a green run
from this tool means:

* A field reported UNCOVERED is uncovered. The trace is a complete record of
  every intent that reached the gate, so zero observations of a non-default
  value is a fact about the run, not an inference.
* A field reported COVERED is covered *in the run that produced the trace*.
  It says nothing about a different corpus, and nothing about whether the
  values seen were varied enough to exercise both sides of a branch. The
  CONSTANT flag is the partial answer to the second: a field populated with a
  single value all run cannot discriminate between two behaviours either.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

UNCOVERED = "UNCOVERED"
CONSTANT = "CONSTANT"
COVERED = "COVERED"
UNREAD = "UNREAD"

_NO_DEFAULT = object()


# --------------------------------------------------------------------------
# The declared surface: what the decision function says its inputs are.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class DeclaredField:
    """One field of the decision function's input value object."""

    name: str
    default_repr: str | None
    read: bool
    gates: tuple[str, ...]
    short_circuits: bool


@dataclass(frozen=True)
class DeclaredSurface:
    intent_class: str
    decide_function: str
    fields: tuple[DeclaredField, ...]

    def by_name(self, name: str) -> DeclaredField | None:
        for entry in self.fields:
            if entry.name == name:
                return entry
        return None


def _default_repr(node: ast.expr | None) -> str | None:
    if node is None:
        return None
    return ast.unparse(node)


def _intent_parameter(func: ast.FunctionDef) -> str:
    """The name the decision function binds its input object to."""

    args = func.args.posonlyargs + func.args.args
    if not args:
        raise ValueError(f"{func.name} takes no positional parameter to analyse")
    return args[0].arg


def _returned_trigger(node: ast.Return) -> str | None:
    """Name the trigger a ``return Decision(...)`` statement fires, if any."""

    call = node.value
    if not isinstance(call, ast.Call):
        return None
    for keyword in call.keywords:
        if keyword.arg == "trigger":
            return ast.unparse(keyword.value)
    return None


def _reads_in(node: ast.AST, param: str, taint: dict[str, set[str]] | None = None) -> set[str]:
    """Field names read off ``param`` anywhere under ``node``.

    ``taint`` carries locals that were assigned from intent fields earlier in
    the function, so a branch testing ``undeclared`` is credited to the field
    that built it. Without this, every field consumed through a local
    intermediate looks like it gates nothing.
    """

    found: set[str] = set()
    for sub in ast.walk(node):
        if (
            isinstance(sub, ast.Attribute)
            and isinstance(sub.value, ast.Name)
            and sub.value.id == param
        ):
            found.add(sub.attr)
        elif taint and isinstance(sub, ast.Name) and sub.id in taint:
            found |= taint[sub.id]
    return found


def _local_taint(func: ast.FunctionDef, param: str) -> dict[str, set[str]]:
    """Locals assigned from intent fields, resolved to a fixpoint."""

    taint: dict[str, set[str]] = {}
    for _ in range(len(func.body) + 1):
        changed = False
        for sub in ast.walk(func):
            if not isinstance(sub, ast.Assign) or sub.value is None:
                continue
            sources = _reads_in(sub.value, param, taint)
            if not sources:
                continue
            for target in sub.targets:
                if not isinstance(target, ast.Name):
                    continue
                before = set(taint.get(target.id, ()))
                taint.setdefault(target.id, set()).update(sources)
                changed |= taint[target.id] != before
        if not changed:
            break
    return taint


def parse_declared_surface(
    source_path: Path, *, intent_class: str, decide_function: str
) -> DeclaredSurface:
    """Read a decision module's own source for its declared input surface."""

    tree = ast.parse(source_path.read_text(encoding="utf-8"), str(source_path))

    class_node: ast.ClassDef | None = None
    func_node: ast.FunctionDef | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == intent_class:
            class_node = node
        elif isinstance(node, ast.FunctionDef) and node.name == decide_function:
            func_node = node
    if class_node is None:
        raise LookupError(f"no class {intent_class!r} in {source_path}")
    if func_node is None:
        raise LookupError(f"no function {decide_function!r} in {source_path}")

    param = _intent_parameter(func_node)
    taint = _local_taint(func_node, param)
    read = _reads_in(func_node, param, taint)

    # A field "gates" a trigger when it is read in a branch that can return
    # that trigger, and "short-circuits" when it is read in a branch that
    # returns before any trigger is consulted. Both matter: an ungated input
    # with no coverage leaves a trigger untested, while an uncovered
    # short-circuit input means the harness took an exit from the whole gate.
    gating: dict[str, set[str]] = {}
    short_circuit: set[str] = set()
    for sub in ast.walk(func_node):
        if not isinstance(sub, ast.If):
            continue
        returns = [stmt for stmt in ast.walk(sub) if isinstance(stmt, ast.Return)]
        triggers = {
            trigger
            for stmt in returns
            for trigger in (_returned_trigger(stmt),)
            if trigger is not None
        }
        touched = _reads_in(sub.test, param, taint) | {
            name for body in sub.body for name in _reads_in(body, param, taint)
        }
        if triggers:
            for name in touched:
                gating.setdefault(name, set()).update(triggers)
        elif returns:
            short_circuit |= _reads_in(sub.test, param, taint)

    fields: list[DeclaredField] = []
    for stmt in class_node.body:
        if not isinstance(stmt, ast.AnnAssign) or not isinstance(stmt.target, ast.Name):
            continue
        name = stmt.target.id
        fields.append(
            DeclaredField(
                name=name,
                default_repr=_default_repr(stmt.value),
                read=name in read,
                gates=tuple(sorted(gating.get(name, ()))),
                short_circuits=name in short_circuit,
            )
        )
    return DeclaredSurface(
        intent_class=intent_class,
        decide_function=decide_function,
        fields=tuple(fields),
    )


# --------------------------------------------------------------------------
# The covered surface: what a harness actually populated, from one run's trace.
# --------------------------------------------------------------------------


@dataclass
class FieldCoverage:
    name: str
    observations: int = 0
    populated: int = 0
    distinct: set[str] = field(default_factory=set)


def _is_default(value: object, default_repr: str | None) -> bool:
    """Whether an observed value is indistinguishable from the declared default.

    A field with no default is never defaulted. Defaults are compared by the
    repr of their literal, which covers the only forms a frozen value object
    uses in practice: ``None``, ``()``, ``0``, ``''``, ``False``.
    """

    if default_repr is None:
        return False
    if default_repr == "None":
        return value is None
    if default_repr in {"()", "[]", "tuple()", "frozenset()"}:
        return value in ((), [], None)
    return repr(value) == default_repr


def load_trace(
    trace_path: Path, surface: DeclaredSurface
) -> tuple[dict[str, FieldCoverage], int]:
    """Fold a JSONL trace of observed intents into per-field coverage."""

    coverage = {entry.name: FieldCoverage(entry.name) for entry in surface.fields}
    records = 0
    for line_no, line in enumerate(
        trace_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = line.strip()
        if not line:
            continue
        try:
            intent = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{trace_path}:{line_no}: {exc}") from exc
        if not isinstance(intent, dict):
            raise ValueError(f"{trace_path}:{line_no}: expected a JSON object")
        records += 1
        unknown = set(intent) - set(coverage)
        if unknown:
            raise ValueError(
                f"{trace_path}:{line_no}: trace carries fields the decision "
                f"surface does not declare: {', '.join(sorted(unknown))}"
            )
        for name, cell in coverage.items():
            if name not in intent:
                continue
            cell.observations += 1
            declared = surface.by_name(name)
            value = intent[name]
            if not _is_default(value, declared.default_repr if declared else None):
                cell.populated += 1
                cell.distinct.add(json.dumps(value, sort_keys=True, default=str))
    return coverage, records


# --------------------------------------------------------------------------
# The intersection.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Row:
    name: str
    read: bool
    gates: tuple[str, ...]
    short_circuits: bool
    observations: int
    populated: int
    distinct: int
    status: str

    @property
    def blind(self) -> bool:
        return self.read and self.status == UNCOVERED


def intersect(surface: DeclaredSurface, coverage: dict[str, FieldCoverage]) -> list[Row]:
    rows: list[Row] = []
    for entry in surface.fields:
        cell = coverage[entry.name]
        if not entry.read:
            status = UNREAD
        elif cell.populated == 0:
            status = UNCOVERED
        elif len(cell.distinct) == 1:
            status = CONSTANT
        else:
            status = COVERED
        rows.append(
            Row(
                name=entry.name,
                read=entry.read,
                gates=entry.gates,
                short_circuits=entry.short_circuits,
                observations=cell.observations,
                populated=cell.populated,
                distinct=len(cell.distinct),
                status=status,
            )
        )
    return rows


def _role(row: Row) -> str:
    parts = list(row.gates)
    if row.short_circuits:
        parts.append("short-circuit")
    return ",".join(parts) or "-"


def render(rows: list[Row], *, records: int, label: str) -> str:
    header = ("input", "read", "role", "populated", "distinct", "status")
    body = [
        (
            row.name,
            "yes" if row.read else "no",
            _role(row),
            f"{row.populated}/{row.observations}",
            str(row.distinct),
            row.status,
        )
        for row in rows
    ]
    widths = [
        max(len(header[i]), *(len(line[i]) for line in body)) for i in range(len(header))
    ]
    def line(cells: tuple[str, ...]) -> str:
        return "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(cells)).rstrip()

    out = [f"blindspot: {label}", f"writes traced: {records}", "", line(header)]
    out.append("  ".join("-" * width for width in widths))
    out.extend(line(cells) for cells in body)
    blind = [row for row in rows if row.blind]
    out.append("")
    if blind:
        out.append(f"{len(blind)} declared input(s) with ZERO coverage:")
        for row in blind:
            out.append(f"  {row.name} -- {_role(row)} -- unfalsifiable by this harness")
    else:
        out.append("every declared input this function reads was populated at least once")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="blindspot",
        description="Intersect a decision function's declared inputs with what a "
        "benchmark harness actually populates.",
    )
    parser.add_argument("--module", required=True, type=Path)
    parser.add_argument("--intent-class", default="WriteIntent")
    parser.add_argument("--decide", default="decide")
    parser.add_argument("--trace", required=True, type=Path)
    parser.add_argument("--label", default="")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    surface = parse_declared_surface(
        args.module, intent_class=args.intent_class, decide_function=args.decide
    )
    coverage, records = load_trace(args.trace, surface)
    rows = intersect(surface, coverage)
    label = args.label or f"{args.module.name}:{args.intent_class} x {args.trace.name}"

    if args.as_json:
        print(
            json.dumps(
                {
                    "label": label,
                    "records": records,
                    "rows": [row.__dict__ | {"gates": list(row.gates)} for row in rows],
                    "blindspots": [row.name for row in rows if row.blind],
                },
                indent=2,
            )
        )
    else:
        print(render(rows, records=records, label=label))

    return 1 if any(row.blind for row in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
