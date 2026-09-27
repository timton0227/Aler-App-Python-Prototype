"""Recount the checkboxes in PROGRESS.md and rewrite its Status table.

Run after ticking a step:

    python3 tools/update_status.py

Counting by hand drifts; this keeps the table and "Next step" honest.
"""
import re
from pathlib import Path

PROGRESS = Path(__file__).resolve().parent.parent / "PROGRESS.md"

PHASE = re.compile(r"^## Phase (\d+) — (.+)$")
STEP = re.compile(r"^- \[(.)\] (\d+\.\d+) ")


def main() -> None:
    text = PROGRESS.read_text()
    phases: list[tuple[str, str, int, int]] = []
    next_step = None
    current = None
    for line in text.splitlines():
        if m := PHASE.match(line):
            current = [m.group(1), m.group(2), 0, 0]
            phases.append(current)
        elif (m := STEP.match(line)) and current is not None:
            current[3] += 1
            if m.group(1) == "x":
                current[2] += 1
            elif next_step is None:
                next_step = m.group(2)

    rows = ["| Phase | Done | Total |", "|---|---|---|"]
    for number, title, done, total in phases:
        short = re.sub(r"\s*\(.*\)$", "", title)
        rows.append(f"| {number} {short} | {done} | {total} |")
    done = sum(p[2] for p in phases)
    total = sum(p[3] for p in phases)
    rows.append(f"| **All** | **{done}** | **{total}** |")

    table = re.compile(r"\| Phase \| Done \| Total \|\n(?:\|.*\|\n)+")
    text = table.sub("\n".join(rows) + "\n", text, count=1)
    text = re.sub(r"\*\*Next step:\*\* .*", f"**Next step:** {next_step or 'none — all done'}", text, count=1)
    PROGRESS.write_text(text)
    print(f"{done}/{total} steps done. Next step: {next_step or 'none'}")


if __name__ == "__main__":
    main()
