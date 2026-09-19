import type { SVGProps } from "react";

// Hand-rolled 16px stroke icons. A whole icon package would be a dependency
// added for ~15 glyphs; these share one grid, one stroke weight and one cap
// style, which is what actually makes an icon set look intentional.

type IconProps = SVGProps<SVGSVGElement>;

function Icon({ children, ...rest }: IconProps) {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.35"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...rest}
    >
      {children}
    </svg>
  );
}

export const IconOverview = (p: IconProps) => (
  <Icon {...p}>
    <path d="M2.5 9.5a5.5 5.5 0 0 1 11 0" />
    <path d="M8 9.5 10.6 6.6" />
    <path d="M2.5 12.5h11" />
  </Icon>
);

export const IconTopology = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="8" cy="3.4" r="1.7" />
    <circle cx="3.2" cy="11.6" r="1.7" />
    <circle cx="12.8" cy="11.6" r="1.7" />
    <path d="M6.7 4.9 4.4 10.1M9.3 4.9l2.3 5.2M4.9 11.6h6.2" />
  </Icon>
);

export const IconActivity = (p: IconProps) => (
  <Icon {...p}>
    <path d="M1.8 8h2.6l1.7-4.6 2.5 9.2L10.3 8h3.9" />
  </Icon>
);

export const IconMetrics = (p: IconProps) => (
  <Icon {...p}>
    <path d="M2.5 13.5v-4M6.5 13.5V5M10.5 13.5V8.5M14 13.5v-11" opacity=".95" />
  </Icon>
);

export const IconShield = (p: IconProps) => (
  <Icon {...p}>
    <path d="M8 1.9 13 3.6v4.1c0 3-2 5.4-5 6.4-3-1-5-3.4-5-6.4V3.6L8 1.9Z" />
  </Icon>
);

export const IconShieldCheck = (p: IconProps) => (
  <Icon {...p}>
    <path d="M8 1.9 13 3.6v4.1c0 3-2 5.4-5 6.4-3-1-5-3.4-5-6.4V3.6L8 1.9Z" />
    <path d="m5.9 7.8 1.5 1.5 2.8-3" />
  </Icon>
);

export const IconWrench = (p: IconProps) => (
  <Icon {...p}>
    <path d="M10.4 2.2a3.4 3.4 0 0 0-3.9 4.4l-4 4a1.3 1.3 0 0 0 1.9 1.9l4-4a3.4 3.4 0 0 0 4.4-3.9L11 6.5 9.5 5l1.9-2.8Z" />
  </Icon>
);

export const IconHistory = (p: IconProps) => (
  <Icon {...p}>
    <path d="M2.6 8a5.4 5.4 0 1 0 1.7-3.9" />
    <path d="M2.3 2.6v3h3" />
    <path d="M8 5.2V8l2 1.4" />
  </Icon>
);

export const IconPlay = (p: IconProps) => (
  <Icon {...p}>
    <path d="M5 3.4 12 8l-7 4.6V3.4Z" fill="currentColor" />
  </Icon>
);

export const IconPause = (p: IconProps) => (
  <Icon {...p}>
    <path d="M5.5 3.5v9M10.5 3.5v9" strokeWidth="1.8" />
  </Icon>
);

export const IconRestart = (p: IconProps) => (
  <Icon {...p}>
    <path d="M13.4 8a5.4 5.4 0 1 1-1.7-3.9" />
    <path d="M13.7 2.6v3h-3" />
  </Icon>
);

export const IconClose = (p: IconProps) => (
  <Icon {...p}>
    <path d="m4 4 8 8M12 4l-8 8" />
  </Icon>
);

export const IconChevronRight = (p: IconProps) => (
  <Icon {...p}>
    <path d="m6 3.5 4.5 4.5L6 12.5" />
  </Icon>
);

export const IconChevronDown = (p: IconProps) => (
  <Icon {...p}>
    <path d="m3.5 6 4.5 4.5L12.5 6" />
  </Icon>
);

export const IconArrowLeft = (p: IconProps) => (
  <Icon {...p}>
    <path d="M12.5 8h-9M7 3.5 2.5 8 7 12.5" />
  </Icon>
);

export const IconSearch = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="7.2" cy="7.2" r="4.2" />
    <path d="m10.4 10.4 3 3" />
  </Icon>
);

export const IconTarget = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="8" cy="8" r="5.5" />
    <circle cx="8" cy="8" r="2" />
  </Icon>
);

export const IconLayers = (p: IconProps) => (
  <Icon {...p}>
    <path d="M8 1.8 14 5 8 8.2 2 5l6-3.2Z" />
    <path d="m2 8.4 6 3.2 6-3.2" />
    <path d="m2 11.4 6 3.2 6-3.2" />
  </Icon>
);

export const IconAlert = (p: IconProps) => (
  <Icon {...p}>
    <path d="M8 2.6 14.4 13H1.6L8 2.6Z" />
    <path d="M8 6.6v3M8 11.4h.01" />
  </Icon>
);

export const IconSpark = (p: IconProps) => (
  <Icon {...p}>
    <path d="M8 1.6 9.5 6 14 7.5 9.5 9 8 13.4 6.5 9 2 7.5 6.5 6 8 1.6Z" />
  </Icon>
);

/** The product mark. A shield split by a network edge — the two things this
 * product is about, in one 20px glyph. */
export function BrandMark({ className }: { className?: string }) {
  return (
    <svg
      width="22"
      height="22"
      viewBox="0 0 22 22"
      fill="none"
      aria-hidden="true"
      className={className}
    >
      <path
        d="M11 2.2 18.4 4.7v6.1c0 4.3-3 7.8-7.4 9.2-4.4-1.4-7.4-4.9-7.4-9.2V4.7L11 2.2Z"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinejoin="round"
      />
      <circle cx="11" cy="6.9" r="1.5" fill="currentColor" />
      <circle cx="7.4" cy="13.2" r="1.5" fill="currentColor" opacity=".55" />
      <circle cx="14.6" cy="13.2" r="1.5" fill="currentColor" opacity=".55" />
      <path
        d="M10 8.2 8.4 11.8M12 8.2l1.6 3.6M8.9 13.2h4.2"
        stroke="currentColor"
        strokeWidth="1.15"
        strokeLinecap="round"
        opacity=".75"
      />
    </svg>
  );
}
