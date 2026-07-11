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
}

const BASE = '/plugin/explosives/api';

export const urls = {
  locationNEQ: (id: number | string) => `${BASE}/location/${id}/neq/`,
  locationSummary: () => `${BASE}/location/summary/`,
  part: (id: number | string) => `${BASE}/part/${id}/`,
  bootstrap: () => `${BASE}/bootstrap/`
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
