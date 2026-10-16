from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from tests.unit.test_local_kernel_execution import run_local_kernel_with_agent_choice
from vgo_runtime.kernel.executor import WorkUnitResult
from vgo_runtime.kernel.loop import run_local_kernel
from vgo_runtime.kernel.task_card import TaskCard
from vgo_runtime.kernel.work_plan import WorkUnit


@pytest.fixture
def agent_root(tmp_path: Path) -> Path:
    agent = tmp_path / "agent-root"
    skill_file = agent / "vibe/skills/local/write-report/SKILL.md"
    skill_file.parent.mkdir(parents=True)
    skill_file.write_text(
        """---
name: Write Report
description: Turn results into a concise report, summary, or briefing.
inputs:
  - results
outputs:
  - report
  - summary
  - briefing
---

# Report workflow

Use verified results to write the report, summary, or briefing.
""",
        encoding="utf-8",
    )
    return agent


def _completed_result(unit: WorkUnit, work_root: Path, content: str) -> WorkUnitResult:
    work_root.mkdir(parents=True, exist_ok=True)
    artifact = work_root / "result.md"
    artifact.write_text(content, encoding="utf-8")
    receipt = work_root / "execution-receipt.json"
    receipt.write_text("{}\n", encoding="utf-8")
    return WorkUnitResult(
        work_unit_id=unit.id,
        status="completed",
        lifecycle_state="executed",
        used_skill=unit.preferred_skill,
        artifacts=unit.expected_artifacts,
        artifact_paths=(str(artifact.resolve()),),
        proof_artifact_paths=(),
        checked_targets=unit.verification,
        notes=("deterministic test execution",),
        proof=(
            f"{unit.id}: used skill {unit.preferred_skill}",
            *(f"{unit.id}: artifact {item}" for item in unit.expected_artifacts),
            *(f"{unit.id}: checked {target}" for target in unit.verification),
        ),
        execution_receipt_path=str(receipt.resolve()),
        artifact_kind="final",
        proof_ready=True,
    )


@pytest.mark.parametrize("field", ["constraints", "known_context", "unknowns"])
@pytest.mark.parametrize("revision_mode", ["replace", "extend"])
def test_resume_rebuilds_report_when_task_inputs_change(
    agent_root: Path, monkeypatch: pytest.MonkeyPatch, field: str, revision_mode: str,
) -> None:
    calls: list[str] = []

    def execute(agent: Path, task: TaskCard, unit: WorkUnit, *, work_root: Path) -> WorkUnitResult:
        calls.append(unit.id)
        return _completed_result(unit, work_root, json.dumps(list(getattr(task, field))))

    monkeypatch.setattr("vgo_runtime.kernel.loop.execute_work_unit", execute)
    arguments = dict(
        agent_root=agent_root,
        run_id="changed-requirement",
        prompt="Produce a report about the benchmark results.",
    )
    first = run_local_kernel_with_agent_choice(
        **arguments, context={"deliverables": ["report"], field: ["Data version A"]}
    )
    assert first["verification"]["result"] == "done"
    resumed = run_local_kernel_with_agent_choice(
        **arguments,
        context={"deliverables": ["report"], field: ["Data version B"], "revision_mode": revision_mode},
    )
    report = Path(resumed["work_results"]["work_results"][0]["artifact_paths"][0])
    expected = ["Data version B"] if revision_mode == "replace" else ["Data version A", "Data version B"]
    assert json.loads(report.read_text(encoding="utf-8")) == expected
    assert calls == ["wu-1", "wu-1"]
    assert resumed["reused_work_units"] == []
    assert resumed["verification"]["result"] == "done"


@pytest.mark.parametrize("missing_field", [None, "task_input_sha256", "dependency_output_sha256"])
def test_resume_reuses_only_complete_current_fingerprints(
    agent_root: Path, monkeypatch: pytest.MonkeyPatch, missing_field: str | None,
) -> None:
    calls: list[str] = []

    def execute(agent: Path, task: TaskCard, unit: WorkUnit, *, work_root: Path) -> WorkUnitResult:
        calls.append(unit.id)
        return _completed_result(unit, work_root, f"Report execution {len(calls)}")

    monkeypatch.setattr("vgo_runtime.kernel.loop.execute_work_unit", execute)
    arguments = dict(agent_root=agent_root, run_id="unchanged-inputs", prompt="Produce a report.")
    first = run_local_kernel_with_agent_choice(**arguments)
    result_path = Path(first["artifacts"]["work_results"])
    if missing_field is not None:
        stored = json.loads(result_path.read_text(encoding="utf-8"))
        stored["work_results"][0].pop(missing_field, None)
        result_path.write_text(json.dumps(stored), encoding="utf-8")
    resumed = run_local_kernel_with_agent_choice(**arguments)
    result = resumed["work_results"]["work_results"][0]
    assert len(calls) == (1 if missing_field is None else 2)
    assert resumed["reused_work_units"] == (["wu-1"] if missing_field is None else [])
    assert result["artifact_kind"] == "final"
    assert result["proof_ready"] is True
    assert len(result["task_input_sha256"]) == 64
    assert len(result["dependency_output_sha256"]) == 64
    assert resumed["verification"]["result"] == "done"


@pytest.mark.parametrize("downstream_count", [1, 2])
@pytest.mark.parametrize("mutation", ["none", "upstream_artifact", "dependent_fingerprint"])
def test_resume_validates_dependency_fingerprints(
    agent_root: Path, monkeypatch: pytest.MonkeyPatch, downstream_count: int, mutation: str,
) -> None:
    produced: dict[str, Path] = {}
    calls: list[str] = []
    version = "A"

    def execute(agent: Path, task: TaskCard, unit: WorkUnit, *, work_root: Path) -> WorkUnitResult:
        calls.append(unit.id)
        content = "summary version " + version
        if unit.depends_on:
            content = "based on: " + produced[unit.depends_on[0]].read_text(encoding="utf-8")
        result = _completed_result(unit, work_root, content)
        produced[unit.id] = Path(result.artifact_paths[0])
        return result

    monkeypatch.setattr("vgo_runtime.kernel.loop.execute_work_unit", execute)
    deliverables = ["summary", "report", "briefing"][:downstream_count + 1]
    arguments = dict(
        agent_root=agent_root,
        run_id="changed-dependency",
        prompt="Produce a summary, report, and briefing about the benchmark results.",
        context={"deliverables": deliverables},
    )
    first = run_local_kernel_with_agent_choice(**arguments)
    assert first["verification"]["result"] == "done"
    if mutation == "upstream_artifact":
        produced["wu-1"].write_text("external edit triggers upstream refresh", encoding="utf-8")
        version = "B"
    elif mutation == "dependent_fingerprint":
        results_path = Path(first["artifacts"]["work_results"])
        stored = json.loads(results_path.read_text(encoding="utf-8"))
        stored["work_results"][1]["dependency_output_sha256"] = "0" * 64
        results_path.write_text(json.dumps(stored), encoding="utf-8")
    resumed = run_local_kernel_with_agent_choice(**arguments)
    for path in produced.values():
        assert "summary version " + version in path.read_text(encoding="utf-8")
    unit_ids = [f"wu-{index}" for index in range(1, len(deliverables) + 1)]
    rerun_ids = [] if mutation == "none" else unit_ids if mutation == "upstream_artifact" else unit_ids[1:]
    assert calls == unit_ids + rerun_ids
    expected_reused = [unit_id for unit_id in unit_ids if unit_id not in rerun_ids]
    assert resumed["reused_work_units"] == expected_reused
    assert resumed["verification"]["result"] == "done"
    plan_reused = [unit["id"] for unit in resumed["plan"]["work_units"] if unit["lifecycle_state"] == "reused"]
    assert plan_reused == expected_reused


def test_resume_preserves_independent_work_and_blocks_failed_dependents(
    agent_root: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    produced: dict[str, Path] = {}
    calls: list[str] = []
    fail_upstream = False

    def execute(agent: Path, task: TaskCard, unit: WorkUnit, *, work_root: Path) -> WorkUnitResult:
        calls.append(unit.id)
        result = _completed_result(unit, work_root, f"{unit.id} execution {len(calls)}")
        produced[unit.id] = Path(result.artifact_paths[0])
        if fail_upstream and unit.id == "wu-1":
            return replace(result, status="failed", failure_reason="upstream data is unavailable")
        return result

    organization = {
        "schema_version": "agent_skill_organization_v1",
        "derived_by": "agent",
        "modules": [
            {
                "module_id": module_id,
                "execution_mode": "agent_direct",
                "depends_on": depends_on,
                "acceptance_criteria": [
                    {
                        "criterion_id": module_id + "-result",
                        "description": "Produce the requested artifact.",
                        "verification_mode": "automated",
                    }
                ],
            }
            for module_id, depends_on in [("wu-1", []), ("wu-2", ["wu-1"]), ("wu-3", [])]
        ],
        "selected_skills": [],
        "uncovered_modules": [],
    }
    monkeypatch.setattr("vgo_runtime.kernel.loop.execute_work_unit", execute)
    arguments = dict(
        agent_root=agent_root,
        run_id="failed-dependency",
        prompt="Produce a summary, report, and briefing.",
        context={"deliverables": ["summary", "report", "briefing"]},
        agent_skill_organization=organization,
    )
    first = run_local_kernel(**arguments)
    assert first["verification"]["result"] == "done"
    produced["wu-1"].write_text("changed upstream", encoding="utf-8")
    fail_upstream = True
    resumed = run_local_kernel(**arguments)
    assert calls == ["wu-1", "wu-3", "wu-2", "wu-1"]
    assert resumed["reused_work_units"] == ["wu-3"]
    by_id = {result["work_unit_id"]: result for result in resumed["work_results"]["work_results"]}
    assert by_id["wu-2"]["status"] == "blocked"
    assert by_id["wu-2"]["artifact_paths"] == ()
    assert by_id["wu-2"]["proof_ready"] is False
    assert resumed["verification"]["result"] != "done"
