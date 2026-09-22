import type { InvenTreePluginContext } from '@inventreedb/ui';

/** One stock item's contribution to a magazine total. */
export interface StockItemNEQ {
  stock_item_id: number;
  part_id: number;
  part_name: string;
  location_id: number | null;
  location_name: string | null;
  quantity: number;
  neq_per_unit_kg: number | null;
  neq_total_kg: number | null;
  division: string | null;
  compatibility_group: string | null;
  classification_code: string | null;
  un_number: string | null;
}

/** Aggregate NEQ for a storage location, against its licensed limit. */
export interface LocationNEQ {
  location_id: number;
  location_name: string;
  neq_kg: number;
  gross_mass_kg: number;
  /** null when the location has no licence limit set. */
  limit_kg: number | null;
  utilisation: number | null;
  over_limit: boolean;
  include_sublocations: boolean;
  by_division: Record<string, number>;
  items: StockItemNEQ[];
  config_errors?: string[];
}

export interface PartExplosive {
  is_explosive: boolean;
  neq_per_unit_kg: number | null;
  gross_mass_per_unit_kg: number | null;
  division: string | null;
  compatibility_group: string | null;
  classification_code: string | null;
  un_number: string | null;
  proper_shipping_name: string | null;
  issues: string[];
  /** Vocabularies for the edit form's selects. */
  divisions?: string[];
  compatibility_groups?: string[];
}

/** Editable explosive properties of a part (PATCH body). All fields optional. */
export interface PartExplosiveUpdate {
  is_explosive?: boolean;
  neq_per_unit_kg?: string;
  gross_mass_per_unit_kg?: string;
  division?: string;
  compatibility_group?: string;
  un_number?: string;
  proper_shipping_name?: string;
}

/** PATCH body for a location's licensed limit. Blank removes it. */
export interface LocationLimitUpdate {
  limit_kg: string;
}

/** Presence and fitness of one parameter template. */
export interface TemplateStatus {
  name: string;
  present: boolean;
  ok: boolean;
}

/** Read-only health of the plugin's parameter templates. */
export interface BootstrapStatus {
  ready: boolean;
  errors: string[];
  templates: TemplateStatus[];
}

const BASE = '/plugin/explosives/api';

export const urls = {
  locationNEQ: (id: number | string) => `${BASE}/location/${id}/neq/`,
  locationSummary: () => `${BASE}/location/summary/`,
  part: (id: number | string) => `${BASE}/part/${id}/`,
  bootstrap: () => `${BASE}/bootstrap/`,
  // Same endpoint as bootstrap(); GET reports status, POST runs setup.
  bootstrapStatus: () => `${BASE}/bootstrap/`
};

/**
 * Fetch from the plugin API.
 *
 * These endpoints only exist when the global ENABLE_PLUGINS_URL setting is on,
 * so a 404 here usually means a configuration problem rather than missing data.
 * We let the error propagate so the panel can say so explicitly.
 */
export async function fetchJson<T>(
  context: InvenTreePluginContext,
  url: string
): Promise<T> {
  const response = await context.api.get(url);
  return response.data as T;
}

/** PATCH a part's explosive properties. Returns the updated properties. */
export async function patchPart(
  context: InvenTreePluginContext,
  partId: number | string,
  payload: PartExplosiveUpdate
): Promise<PartExplosive> {
  const response = await context.api.patch(urls.part(partId), payload);
  return response.data as PartExplosive;
}

/** PATCH a location's licensed NEQ limit. */
export async function patchLocationLimit(
  context: InvenTreePluginContext,
  locationId: number | string,
  payload: LocationLimitUpdate
): Promise<LocationNEQ> {
  const response = await context.api.patch(
    urls.locationNEQ(locationId),
    payload
  );
  return response.data as LocationNEQ;
}

/** Flatten a DRF error body (dict of field->messages, or a list) into strings. */
export function errorMessages(detail: unknown): string[] {
  if (!detail) {
    return ['Save failed.'];
  }
  if (Array.isArray(detail)) {
    return detail.map(String);
  }
  if (typeof detail === 'object') {
    return Object.values(detail as Record<string, unknown>)
      .flat()
      .map(String);
  }
  return [String(detail)];
}

/** Format a mass in kg for display. */
export function kg(value: number | null | undefined, places = 3): string {
  if (value === null || value === undefined) {
    return '—';
  }
  return `${value.toFixed(places)} kg`;
}

/** Colour for a utilisation ratio: green under 80%, amber to 100%, red over. */
export function utilisationColor(
  utilisation: number | null,
  overLimit: boolean
): string {
  if (overLimit) {
    return 'red';
  }
  if (utilisation === null) {
    return 'gray';
  }
  if (utilisation >= 0.8) {
    return 'orange';
  }
  return 'green';
}
