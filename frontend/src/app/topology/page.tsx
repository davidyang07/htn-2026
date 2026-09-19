"use client";

import { TopologyWorkspace } from "@/components/graph/TopologyWorkspace";
import { PageHeader } from "@/components/shell/AppShell";
import { RequiresRun } from "@/components/shell/RequiresRun";
import { useExperiment } from "@/lib/experiment/ExperimentProvider";
import { useSecurityInsights } from "@/lib/security/useSecurityInsights";

export default function TopologyPage() {
  return (
    <RequiresRun
      title="No system mapped yet"
      description="The topology view renders the typed security graph of a running assessment — agents, tools, credentials, resources and the security plane watching them."
    >
      {(experimentId) => <TopologyContent experimentId={experimentId} />}
    </RequiresRun>
  );
}

function TopologyContent({ experimentId }: { experimentId: string }) {
  const { stream } = useExperiment();
  const insights = useSecurityInsights(experimentId);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <PageHeader
        eyebrow="Map · Attack paths"
        title="Topology"
        description="Colour is security state; shape and size are node type. Toggle edge layers to isolate communication, access or oversight relationships, then trace a specific attack path between any two nodes."
        className="py-3"
      />
      <TopologyWorkspace
        experimentId={experimentId}
        stream={stream}
        securityGraph={insights.graph}
        blastRadius={insights.blastRadius}
        loading={insights.loading}
      />
    </div>
  );
}
