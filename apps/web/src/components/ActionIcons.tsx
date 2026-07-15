import { createLucideIcon, Share2, type LucideProps } from "lucide-react";

export const BranchFromHereIcon = createLucideIcon("BranchFromHere", [
  ["path", { d: "M4 12h8", key: "branch-origin" }],
  ["path", { d: "M12 12 22 2", key: "upper-branch" }],
  ["path", { d: "M16 2h6v6", key: "upper-arrow" }],
  ["path", { d: "m12 12 10 10", key: "lower-branch" }],
  ["path", { d: "M16 22h6v-6", key: "lower-arrow" }],
]);

export function ShareActionIcon({ style, ...props }: LucideProps) {
  return (
    <Share2
      {...props}
      style={{ ...style, transform: "rotate(90deg)", transformOrigin: "center" }}
    />
  );
}
