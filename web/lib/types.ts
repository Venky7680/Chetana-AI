export type Tier = 0 | 1 | 2 | 3;

export interface TenantSummary {
  id: string;
  name: string;
  tags: string[];
  max_autonomy_tier: number;
  effective_ceiling?: number;
}

export interface Me {
  email: string;
  role: string;
  role_level: number;
  tenants: TenantSummary[];
  global_max_autonomy_tier: number;
}

export interface Alert {
  fingerprint: string;
  name: string;
  description: string | null;
  status: string;
  severity: string;
  severity_rank: number;
  source: string[];
  service: string | null;
  environment: string | null;
  last_received: string | null;
  assignee: string | null;
  url: string | null;
  labels: Record<string, unknown>;
  enriched_fields: string[];
}

export interface Incident {
  id: string;
  name: string;
  summary: string | null;
  status: string;
  is_open: boolean;
  severity: string;
  severity_rank: number;
  alerts_count: number;
  services: string[];
  sources: string[];
  assignee: string | null;
  created_at: string | null;
  started_at: string | null;
  last_seen_at: string | null;
  is_candidate: boolean;
  is_predicted: boolean;
  rule_id: string | null;
}

export interface Workflow {
  id: string;
  name: string;
  description: string | null;
  disabled: boolean;
  revision: number | null;
  created_by: string | null;
  triggers: unknown[];
  providers: { type?: string; name?: string }[];
  last_execution_time: string | null;
  last_execution_status: string | null;
}

export interface Envelope<T> {
  items: T[];
  meta: { count: number; limit: number | null; offset: number | null; total: number };
}

export interface Stats {
  alerts_total: number;
  alerts_firing: number;
  alerts_by_severity: Record<string, number>;
  incidents_total: number;
  incidents_open: number;
  alerts_correlated: number;
  noise_reduction_pct: number;
  unassigned_incidents: number;
  critical_open: number;
}

export interface Overview {
  tenant: { id: string; name: string; tags: string[] };
  stats: Stats;
  reachable: boolean;
  problems: string[];
  top_incidents: Incident[];
  recent_alerts: Alert[];
  noisiest_services: { name: string; alerts: number }[];
  autonomy: {
    tenant_ceiling: number;
    global_ceiling: number;
    effective_ceiling: number;
    pending_approvals: number;
  };
}

export interface EstateRow {
  tenant: { id: string; name: string; tags: string[] };
  reachable: boolean;
  problems: string[];
  stats: Partial<Stats>;
  pending_approvals?: number;
}

export interface Capability {
  operation_id: string;
  summary: string;
  tier: number;
  tier_name: string;
  min_role: string;
  decision: "execute" | "approval_required" | "denied";
  reason: string;
  approvals_needed: number;
  effective_ceiling: number;
}

export interface ApprovalRequest {
  id: string;
  tenant_id: string;
  operation_id: string;
  requested_by: string;
  created_at: string;
  expires_at: string;
  tier: number;
  approvals_needed: number;
  approvals: string[];
  satisfied: boolean;
  expired: boolean;
  consumed: boolean;
  note: string;
  target: { path_params: Record<string, string>; query_params: Record<string, unknown> };
}

export interface AuditEntry {
  ts: string;
  actor: string;
  tenant_id: string;
  operation_id: string;
  decision: string;
  reason: string;
  tier: number;
  status: string;
  detail?: Record<string, unknown>;
}

export interface IncidentDetail {
  incident: Incident;
  alerts: Alert[];
  workflow_executions: Record<string, unknown>[];
  degraded: string[];
}

export interface AlertDetail {
  alert: Alert;
  occurrences: Alert[];
  audit: Record<string, unknown>[];
  degraded: string[];
}

export interface WorkflowDetail {
  workflow: Workflow;
  definition: string;
  runs: Record<string, unknown>[];
  degraded: string[];
}

export interface CorrelationRule {
  id: string;
  name: string;
  definition_cel?: string;
  grouping_criteria?: string[];
  timeframe?: number;
  created_by?: string;
  creation_time?: string;
  incidents?: number;
  require_approve?: boolean;
  resolve_on?: string;
}

export interface DedupRule {
  id: string;
  name: string;
  description?: string;
  provider_type?: string;
  provider_id?: string;
  ingested?: number;
  dedup_ratio?: number;
  fingerprint_fields?: string[];
  full_deduplication?: boolean;
  default?: boolean;
}

export interface TopologyService {
  id: number | string;
  service: string;
  display_name?: string;
  environment?: string;
  description?: string;
  team?: string;
  application_ids?: string[];
  dependencies?: { serviceId?: string; serviceName?: string; protocol?: string }[];
}

export interface MaintenanceRule {
  id: string;
  name: string;
  description?: string;
  cel_query?: string;
  start_time?: string;
  end_time?: string;
  duration_seconds?: number;
  enabled?: boolean;
  suppress?: boolean;
  created_by?: string;
}

export interface Preset {
  id: string;
  name: string;
  options?: { label?: string; value?: unknown }[];
  is_private?: boolean;
  should_do_noise_now?: boolean;
  alerts_count?: number;
}

/** One field a provider needs, exactly as Keep describes it. */
export interface ProviderConfigField {
  description?: string;
  hint?: string;
  required?: boolean;
  sensitive?: boolean;
  type?: string;
  default?: unknown;
  validation?: string;
}

/** A permission the credential must carry. Keep validates these at install and
 *  refuses with 412 when a mandatory one is missing. */
export interface ProviderScope {
  name: string;
  description?: string | null;
  mandatory?: boolean;
  mandatory_for_webhook?: boolean;
  documentation_url?: string | null;
}

export interface ProviderCatalogueEntry {
  type: string;
  display_name: string;
  description?: string;
  categories: string[];
  tags: string[];
  can_setup_webhook: boolean;
  supports_webhook: boolean;
  webhook_required?: boolean;
  can_query: boolean;
  can_notify: boolean;
  pulling_available?: boolean;
  coming_soon?: boolean;
  /** Field name -> what Keep says about it. Shapes vary by provider and by Keep
   *  version, so the install form reads it defensively. */
  config?: Record<string, ProviderConfigField>;
  scopes?: ProviderScope[];
  docs_slug?: string | null;
}
