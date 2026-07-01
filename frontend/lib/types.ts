// Mirror of the backend AuditResult shape (aritiq.pipeline.audit -> JSON).

export type Status =
  | "VERIFIED"
  | "WRONG_MATH"
  | "UNSUPPORTED_NUMBER"
  | "AMBIGUOUS"
  | "UNCHECKED"
  // ---- Phase 2 ----
  | "NEEDS_REVIEW" // vague word next to a number; routed to a human
  | "CONFLICT" // two source documents disagree on the same figure
  // ---- Phase 3 ----
  | "PROPAGATED_ERROR" // not independently broken; downstream of a failed claim
  | "INSUFFICIENT_EVIDENCE"; // operands incomplete/wrong-scope; verifier declined to convict

export type RestatementType =
  | "UNCLASSIFIED"
  | "EXPLICIT_RESTATEMENT"
  | "POSSIBLE_RECLASSIFICATION"
  | "UNEXPLAINED";

export type OperandSource =
  | "grounded"
  | "inferred"
  | "missing"
  // ---- Phase 2 provenance ----
  | "grounded_table_cell"
  | "grounded_prose"
  | "category_inferred";

export interface Operand {
  value: number | null; // null for operands the extractor could not locate
  source: OperandSource;
  source_text: string | null;
  source_span: [number, number] | null;
  // ---- Phase 2 optional provenance ----
  doc_id?: string | null; // which registry document this operand came from
  category?: string | null; // inferred category, when source === "category_inferred"
  category_scheme_version?: string | null; // version stamp for drift detection
}

export interface Claim {
  claim_text: string;
  operation: string;
  stated_value: number | null;
  operands: Operand[];
  unit: string | null;
  // ---- Phase 2 optional fields ----
  rule_name?: string | null; // e.g. "balance_sheet_identity"
  eps_variant?: "basic" | "diluted" | null;
  // ---- Phase 3 optional fields ----
  node_id?: string | null;
  depends_on?: string[];
}

export interface Result {
  status: Status;
  recomputed_value: number | null;
  delta: number | null;
  explanation: string;
  claim: Claim;
  // ---- Phase 3 optional fields ----
  caused_by?: string | null; // node_id of the root failure, for PROPAGATED_ERROR
  restatement_type?: RestatementType | null; // disclosure annotation, for CONFLICT
}

export interface Score {
  score: number; // dependency-weighted (primary)
  verified: number;
  wrong_math: number;
  unsupported: number;
  ambiguous: number;
  unchecked: number;
  total_checkable: number;
  // ---- Phase 2 counts ----
  needs_review?: number;
  conflict?: number;
  // ---- Phase 3 ----
  propagated_error?: number;
  insufficient_evidence?: number;
  unweighted_score?: number; // the flat score, shown beside the weighted one
}

export interface Issue {
  message: string;
}

export interface Filing {
  ticker: string;
  company: string;
  cik: number;
  accession: string;
  filing_date: string;
  period?: string | null;
  document_url: string;
  source_chars: number;
}

export interface AuditResult {
  score: Score;
  results: Result[];
  issues: Issue[];
  // ---- Phase 3: cross-document conflicts (also present in results) ----
  conflicts?: Result[];
  // ---- Present only for the by-ticker (SEC EDGAR) flow ----
  filing?: Filing;
}

export interface Example {
  id: string;
  name: string;
  source: string;
  summary: string;
}

// ---- Phase 3 multi-document input ----
export interface DocumentInput {
  doc_id: string;
  text: string;
  period?: string | null;
  doc_type?: string | null;
}
