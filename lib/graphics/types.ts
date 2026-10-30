export type {
  Config_Output as Config,
  Fields,
  Region,
  RunRecord as Run,
  RunSummary,
  GraphicsResult as Result,
  Review_Input as Review,
} from "./contracts.generated.js";
import type { Config_Output } from "./contracts.generated.js";
export type Box = Config_Output["regions"][number];
import type { Fields } from "./contracts.generated.js";
export type RegionDraft = {
  fields: Fields;
  rationale: string;
  candidateId: number | null;
  expectedVersion: number;
};
