export interface Share {
  k: number;
  n: number;
  lower: number;
  upper: number;
}
export interface LandingNumbers {
  source: string;
  date: string;
  model: string;
  items: number;
  labels: { ai_only: boolean; people: string[]; text: string };
  pooled_decided: Share;
  unknown_rate: Share;
  majority_baseline: Share;
  nature_composed: Share;
  nature_rules: Share;
}
export const REPO: string;
export const OUTPUT: string;
export function wilson(k: number, n: number): Share;
export function disclosure(
  items: number,
  labellers: string[],
  adjudicators: (string | null)[],
): LandingNumbers["labels"];
export function computeNumbers(): LandingNumbers;
