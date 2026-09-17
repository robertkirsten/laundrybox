export type Lifecycle =
  | "starting"
  | "waiting"
  | "acquiring"
  | "new_garment"
  | "pass"
  | "check"
  | "unavailable";

export type InspectionCategory =
  | "nothing_found"
  | "scissors"
  | "keys"
  | "money"
  | "paper"
  | "pen"
  | "tissues"
  | "headphones"
  | "tool"
  | "other";

export interface GarmentSnapshot {
  epc: string;
  chute_number: number;
  id_number: string;
  article_number: string;
  product_name: string;
  size: string;
  customer_name: string;
  customer_number: string;
  wearer_name: string;
  wearer_number: string;
  manufacture_year: number;
  manufacture_week: number;
}

export interface MeasurementSnapshot {
  reference_g: number | null;
  measured_g: number | null;
  difference_g: number | null;
  threshold_g: number;
  stable: boolean;
}

export interface DisplaySnapshot {
  revision: number;
  updated_at: string;
  lifecycle: Lifecycle;
  cycle_id: string | null;
  decision: "PASS" | "CHECK" | null;
  reason: string;
  scanned_count: number;
  station: { code: string; name: string };
  operator: { number: string; display_name: string };
  garment: GarmentSnapshot | null;
  measurement: MeasurementSnapshot | null;
  // EPC awaiting operator registration while lifecycle === "new_garment".
  pending_epc: string | null;
  health: {
    backend_ok: boolean;
    database_ok: boolean;
    serial_connected: boolean;
    serial_fresh: boolean;
    rfid_ok: boolean;
    scale_ok: boolean;
  };
  feedback_recorded: boolean;
  feedback_category: InspectionCategory | null;
}

export interface InspectionResponse {
  cycle_id: string;
  category: InspectionCategory;
  recorded_at: string;
  duplicate: boolean;
}

const API_BASE = (
  import.meta.env.VITE_ARGUS_API_BASE ?? "http://127.0.0.1:8000/api/v1"
).replace(/\/$/, "");

async function responseJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: string };
      detail = body.detail ?? detail;
    } catch {
      // A proxy or offline response may not contain JSON.
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

export async function fetchState(
  signal?: AbortSignal,
): Promise<DisplaySnapshot> {
  return responseJson<DisplaySnapshot>(
    await fetch(`${API_BASE}/state`, { signal, cache: "no-store" }),
  );
}

export function openStateEvents(
  onState: (snapshot: DisplaySnapshot) => void,
  onConnectionChange: (connected: boolean) => void,
): EventSource {
  const events = new EventSource(`${API_BASE}/events`);
  events.addEventListener("state", (event) => {
    onState(
      JSON.parse((event as MessageEvent<string>).data) as DisplaySnapshot,
    );
  });
  events.onopen = () => onConnectionChange(true);
  events.onerror = () => onConnectionChange(false);
  return events;
}

export async function postInspection(
  cycleId: string,
  category: InspectionCategory,
): Promise<InspectionResponse> {
  return responseJson<InspectionResponse>(
    await fetch(
      `${API_BASE}/cycles/${encodeURIComponent(cycleId)}/inspection`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ category }),
      },
    ),
  );
}

export interface GarmentRegistration {
  productName?: string;
  wearerName?: string;
}

export async function registerNewGarment(
  cycleId: string,
  action: "register" | "dismiss",
  details: GarmentRegistration = {},
): Promise<DisplaySnapshot> {
  const body =
    action === "register"
      ? {
          action,
          product_name: details.productName?.trim() || null,
          wearer_name: details.wearerName?.trim() || null,
        }
      : { action };
  return responseJson<DisplaySnapshot>(
    await fetch(`${API_BASE}/cycles/${encodeURIComponent(cycleId)}/garment`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
}
