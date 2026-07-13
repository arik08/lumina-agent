import { createLucideIcon, Share2, type LucideProps } from "lucide-react";

export const BranchFromHereIcon = createLucideIcon("BranchFromHere", [
  ["path", { d: "M12 6h5a2 2 0 0 1 2 2v7", key: "upper-branch" }],
  ["path", { d: "m15 9-3-3 3-3", key: "upper-arrow" }],
  ["path", { d: "M12 18H7a2 2 0 0 1-2-2V9", key: "lower-branch" }],
  ["path", { d: "m9 15 3 3-3 3", key: "lower-arrow" }],
]);

export function ShareActionIcon({ style, ...props }: LucideProps) {
  return (
    <Share2
      {...props}
      style={{ ...style, transform: "rotate(90deg)", transformOrigin: "center" }}
    />
  );
}
