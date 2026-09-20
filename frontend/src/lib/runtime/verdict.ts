// What the judge reads off the screen, derived from the live event stream.
//
// Pure, and derived from events rather than from a REST poll, for one reason:
// a verdict light that can be set by anything other than an event that
// actually happened is a light that can lie. `ATTACK DETECTED` turns on
// because a POLICY_VIOLATION arrived, and for no other reason.

import type { Event } from "@/lib/stream/reducer";

export type CompletedStep = {
  step: string;
  workerId: string | null;
  detail: string;
  seq: number;
};

export type DemoVerdict = {
  attackDetected: boolean;
  agentQuarantined: boolean;
  workflowRecovered: boolean;
  /** null until a real test run is reported. false is a genuinely red run. */
  testsPassed: boolean | null;
  /** The real pytest summary line, verbatim. Never synthesized. */
  testSummary: string | null;
  testCommand: string | null;
  quarantinedWorkerId: string | null;
  replacementWorkerId: string | null;
  /** The path that was requested and denied — never any content. */
  deniedResource: string | null;
  violationReason: string | null;
  violationType: string | null;
  recoverySummary: string | null;
  completedSteps: CompletedStep[];
};

export const EMPTY_VERDICT: DemoVerdict = {
  attackDetected: false,
  agentQuarantined: false,
  workflowRecovered: false,
  testsPassed: null,
  testSummary: null,
  testCommand: null,
  quarantinedWorkerId: null,
  replacementWorkerId: null,
  deniedResource: null,
  violationReason: null,
  violationType: null,
  recoverySummary: null,
  completedSteps: [],
};

function str(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

export function deriveVerdict(events: readonly Event[]): DemoVerdict {
  const verdict: DemoVerdict = { ...EMPTY_VERDICT, completedSteps: [] };

  for (const event of events) {
    const meta = (event.metadata ?? {}) as Record<string, unknown>;

    switch (event.event_type) {
      case "POLICY_VIOLATION":
        verdict.attackDetected = true;
        verdict.deniedResource = str(meta["resource"]) ?? verdict.deniedResource;
        verdict.violationReason = str(meta["reason"]) ?? verdict.violationReason;
        verdict.violationType = str(meta["violation_type"]) ?? verdict.violationType;
        break;

      case "AGENT_QUARANTINED":
        verdict.agentQuarantined = true;
        verdict.quarantinedWorkerId = event.agent_id ?? verdict.quarantinedWorkerId;
        break;

      case "AGENT_CREATED":
        if (str(meta["replaces"])) {
          verdict.replacementWorkerId = event.agent_id ?? verdict.replacementWorkerId;
        }
        break;

      case "TASK_COMPLETED": {
        const step = str(meta["step"]);
        if (!step) break;
        verdict.completedSteps.push({
          step,
          workerId: event.agent_id ?? null,
          detail: str(meta["detail"]) ?? "",
          seq: event.seq,
        });
        if (step === "pytest") {
          // A red run is read red. The only thing that sets this true is a
          // run that actually reported passed=true.
          verdict.testsPassed = meta["passed"] === true;
          verdict.testSummary = str(meta["detail"]);
          verdict.testCommand = str(meta["command"]);
        }
        break;
      }

      case "WORKFLOW_RECOVERED":
        verdict.workflowRecovered = true;
        verdict.recoverySummary = str(meta["summary"]);
        break;

      default:
        break;
    }
  }

  return verdict;
}

export type VerdictLight = {
  key: keyof Pick<
    DemoVerdict,
    "attackDetected" | "agentQuarantined" | "workflowRecovered"
  > | "testsPassed";
  label: string;
  /** Lit, not-yet-reached, or explicitly failed. */
  status: "pending" | "lit" | "failed";
  hint: string;
};

export function verdictLights(verdict: DemoVerdict): VerdictLight[] {
  return [
    {
      key: "attackDetected",
      label: "Attack detected",
      status: verdict.attackDetected ? "lit" : "pending",
      hint: verdict.violationReason ?? "No policy violation recorded yet.",
    },
    {
      key: "agentQuarantined",
      label: "Agent quarantined",
      status: verdict.agentQuarantined ? "lit" : "pending",
      hint: verdict.quarantinedWorkerId
        ? `${verdict.quarantinedWorkerId} was removed from the team.`
        : "No worker has been quarantined.",
    },
    {
      key: "workflowRecovered",
      label: "Workflow recovered",
      status: verdict.workflowRecovered ? "lit" : "pending",
      hint: verdict.recoverySummary ?? "The workflow has not completed yet.",
    },
    {
      key: "testsPassed",
      label: "Tests passed",
      status:
        verdict.testsPassed === true
          ? "lit"
          : verdict.testsPassed === false
            ? "failed"
            : "pending",
      hint: verdict.testSummary ?? "No test run reported yet.",
    },
  ];
}
