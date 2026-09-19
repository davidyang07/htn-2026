import type { ComponentType, SVGProps } from "react";

import {
  IconActivity,
  IconHistory,
  IconMetrics,
  IconOverview,
  IconShieldCheck,
  IconTopology,
  IconWrench,
} from "@/components/ui/icons";

export type NavItem = {
  href: string;
  label: string;
  icon: ComponentType<SVGProps<SVGSVGElement>>;
  /** Which step of Map → Attack → Observe → Measure → Remediate → Re-test
   * this screen serves. Shown in the rail so the navigation itself teaches
   * the workflow. */
  stage: string;
  /** Needs an active run to show anything. */
  needsRun?: boolean;
};

export type NavGroup = { label: string; items: NavItem[] };

export const NAV: NavGroup[] = [
  {
    label: "Assess",
    items: [
      { href: "/", label: "Overview", icon: IconOverview, stage: "Posture" },
      { href: "/topology", label: "Topology", icon: IconTopology, stage: "Map", needsRun: true },
      { href: "/activity", label: "Activity", icon: IconActivity, stage: "Observe", needsRun: true },
    ],
  },
  {
    label: "Evaluate",
    items: [
      { href: "/metrics", label: "Metrics", icon: IconMetrics, stage: "Measure", needsRun: true },
      { href: "/defenses", label: "Defenses", icon: IconShieldCheck, stage: "Compare" },
      {
        href: "/remediation",
        label: "Remediation",
        icon: IconWrench,
        stage: "Fix & re-test",
        needsRun: true,
      },
    ],
  },
  {
    label: "Archive",
    items: [{ href: "/history", label: "Runs", icon: IconHistory, stage: "Replay" }],
  },
];

/** Longest-prefix match so `/history/<id>` still highlights "Runs". */
export function isActivePath(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}
