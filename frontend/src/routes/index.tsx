import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState, type ReactNode } from "react";
import {
  Coins,
  FileText,
  Headphones,
  Key,
  Pen,
  Plus,
  Scissors,
  Square,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import { useArgusState } from "@/hooks/use-argus-state";
import {
  postInspection,
  registerNewGarment,
  type DisplaySnapshot,
  type GarmentSnapshot,
  type InspectionCategory,
} from "@/lib/argus-api";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Nordwäsche Check-Station" },
      {
        name: "description",
        content:
          "Schachtanzeige und Hosentaschen-Kontrolle für die industrielle Wäsche.",
      },
    ],
  }),
  component: CheckStation,
});

type InspectionScreen = "result" | "check" | "found";
type FrameStatus = "ok" | "err" | "neutral";

const FOUND_ITEMS: ReadonlyArray<{
  Icon: LucideIcon;
  label: string;
  category: InspectionCategory;
}> = [
  { Icon: Scissors, label: "Schere", category: "scissors" },
  { Icon: Key, label: "Schlüssel", category: "keys" },
  { Icon: Coins, label: "Geld", category: "money" },
  { Icon: FileText, label: "Papier", category: "paper" },
  { Icon: Pen, label: "Stift", category: "pen" },
  { Icon: Square, label: "Taschentücher", category: "tissues" },
  { Icon: Headphones, label: "Kopfhörer", category: "headphones" },
  { Icon: Wrench, label: "Werkzeug", category: "tool" },
  { Icon: Plus, label: "Sonstiges", category: "other" },
];

const REASON_LABELS: Record<string, string> = {
  serial_disconnected: "Teensy nicht verbunden",
  serial_stale: "Keine aktuellen Messdaten",
  teensy_restarted: "Teensy wurde neu gestartet",
  rfid_configuration_error: "RFID-Konfiguration fehlgeschlagen",
  remove_garment_after_restart: "Box leeren und Kleidungsstück entnehmen",
  waiting_for_empty_box: "Box muss zuerst leer sein",
  missing_weight: "Keine Gewichtsmessung verfügbar",
  database_error: "Datenbank nicht verfügbar",
};

function useClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  return now;
}

function TopBar({ snapshot }: { snapshot: DisplaySnapshot | null }) {
  const now = useClock();
  return (
    <div className="flex items-center justify-between border-b border-line px-6 py-2.5 font-mono text-xs tabular-nums text-steel">
      <span className="text-sm text-ink">
        {snapshot?.scanned_count ?? 0} gescannte Teile
      </span>
      <span>
        {snapshot
          ? `${snapshot.operator.display_name} · #${snapshot.operator.number}`
          : "ARGUS · Verbindung wird hergestellt"}
      </span>
      <span>
        {now.toLocaleDateString("de-DE")} · {now.toLocaleTimeString("de-DE")}
      </span>
    </div>
  );
}

function Frame({
  status,
  snapshot,
  children,
}: {
  status: FrameStatus;
  snapshot: DisplaySnapshot | null;
  children: ReactNode;
}) {
  return (
    <div className="min-h-screen bg-paper p-3 font-body text-ink">
      <div
        className={cn(
          "relative flex min-h-[calc(100vh-24px)] flex-col overflow-hidden rounded-2xl border-[10px]",
          status === "ok" && "border-ok bg-ok/5",
          status === "err" && "border-err bg-err/5",
          status === "neutral" && "border-steel bg-panel",
        )}
      >
        <TopBar snapshot={snapshot} />
        {children}
      </div>
    </div>
  );
}

function StatusScreen({
  snapshot,
  title,
  detail,
  status = "neutral",
}: {
  snapshot: DisplaySnapshot | null;
  title: string;
  detail: string;
  status?: FrameStatus;
}) {
  return (
    <Frame status={status} snapshot={snapshot}>
      <div className="flex flex-1 flex-col items-center justify-center px-8 text-center">
        <p className="font-mono text-sm uppercase tracking-[0.25em] text-steel">
          {snapshot?.station.name ?? "ARGUS Check-Station"}
        </p>
        <h1 className="mt-4 font-display text-7xl font-bold uppercase tracking-tight">
          {title}
        </h1>
        <p className="mt-5 max-w-2xl font-mono text-lg text-steel">{detail}</p>
      </div>
    </Frame>
  );
}

function GarmentHeading({ garment }: { garment: GarmentSnapshot | null }) {
  return (
    <p className="font-mono text-sm uppercase tracking-[0.25em] text-steel">
      {garment
        ? `Schacht ${garment.chute_number} · ${garment.product_name}`
        : "Kleidungsstück nicht eindeutig erkannt"}
    </p>
  );
}

function formatWeight(value: number | null | undefined): string {
  if (value === null || value === undefined) return "–";
  const displayValue = Math.abs(value) < 0.05 ? 0 : value;
  return new Intl.NumberFormat("de-DE", {
    minimumFractionDigits: Number.isInteger(displayValue) ? 0 : 1,
    maximumFractionDigits: 1,
    signDisplay: "auto",
  }).format(displayValue);
}

function CheckStation() {
  const { snapshot, connection } = useArgusState();
  const [screen, setScreen] = useState<InspectionScreen>("result");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [productName, setProductName] = useState("");
  const [wearerName, setWearerName] = useState("");

  useEffect(() => {
    setSubmitError(null);
    setProductName("");
    setWearerName("");
    setScreen(snapshot?.lifecycle === "check" ? "check" : "result");
  }, [snapshot?.cycle_id, snapshot?.lifecycle]);

  const submitRegistration = async (action: "register" | "dismiss") => {
    if (!snapshot?.cycle_id || submitting) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      // The resulting PASS/CHECK snapshot arrives over SSE.
      await registerNewGarment(snapshot.cycle_id, action, {
        productName,
        wearerName,
      });
    } catch (error) {
      setSubmitError(
        error instanceof Error
          ? error.message
          : "Kleidungsstück konnte nicht gespeichert werden",
      );
    } finally {
      setSubmitting(false);
    }
  };

  const submitFeedback = async (category: InspectionCategory) => {
    if (!snapshot?.cycle_id || submitting) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      await postInspection(snapshot.cycle_id, category);
      setScreen("result");
    } catch (error) {
      setSubmitError(
        error instanceof Error
          ? error.message
          : "Rückmeldung konnte nicht gespeichert werden",
      );
    } finally {
      setSubmitting(false);
    }
  };

  if (connection === "connecting" && snapshot === null) {
    return (
      <StatusScreen
        snapshot={null}
        title="Verbinde"
        detail="Verbindung wird hergestellt …"
      />
    );
  }

  if (connection === "disconnected") {
    return (
      <StatusScreen
        snapshot={snapshot}
        title="Nicht verbunden"
        detail="Warte auf Backend-Verbindung …"
        status="err"
      />
    );
  }

  if (snapshot === null) {
    return (
      <StatusScreen
        snapshot={null}
        title="Nicht bereit"
        detail="Kein Systemstatus verfügbar."
      />
    );
  }

  if (
    snapshot.lifecycle === "unavailable" ||
    snapshot.lifecycle === "starting"
  ) {
    return (
      <StatusScreen
        snapshot={snapshot}
        title="System nicht bereit"
        detail={REASON_LABELS[snapshot.reason] ?? snapshot.reason}
        status="err"
      />
    );
  }

  if (snapshot.lifecycle === "waiting") {
    return (
      <StatusScreen
        snapshot={snapshot}
        title="Bereit"
        detail="Kleidungsstück einlegen"
      />
    );
  }

  if (snapshot.lifecycle === "acquiring") {
    return (
      <StatusScreen
        snapshot={snapshot}
        title="Messung läuft"
        detail="Bitte nicht berühren …"
      />
    );
  }

  if (snapshot.lifecycle === "new_garment") {
    return (
      <Frame status="neutral" snapshot={snapshot}>
        <div className="flex flex-1 flex-col items-center justify-center gap-7 px-8 py-8 text-center">
          <div>
            <p className="font-mono text-sm uppercase tracking-[0.25em] text-steel">
              Unbekanntes RFID-Tag
            </p>
            <h1 className="mt-3 font-display text-6xl font-bold uppercase tracking-tight">
              Neues Kleidungsstück
            </h1>
            <p className="mt-3 font-mono text-lg text-steel">
              Mit dem gemessenen Gewicht als Referenz aufnehmen?
            </p>
          </div>
          <div className="flex items-baseline gap-3">
            <span className="font-display text-7xl font-bold tabular-nums">
              {formatWeight(snapshot.measurement?.measured_g ?? null)}
            </span>
            <span className="font-mono text-2xl text-steel">g</span>
          </div>
          <div className="w-full max-w-md space-y-4 text-left">
            <label className="block">
              <span className="font-mono text-sm uppercase tracking-wider text-steel">
                Bezeichnung (optional)
              </span>
              <input
                value={productName}
                onChange={(event) => setProductName(event.target.value)}
                placeholder="Neues Kleidungsstück"
                maxLength={160}
                className="mt-1 w-full rounded-xl border-2 border-line bg-paper px-4 py-3 font-body text-xl text-ink outline-none focus:border-steel"
              />
            </label>
            <label className="block">
              <span className="font-mono text-sm uppercase tracking-wider text-steel">
                Träger (optional)
              </span>
              <input
                value={wearerName}
                onChange={(event) => setWearerName(event.target.value)}
                placeholder="Nicht zugeordnet"
                maxLength={160}
                className="mt-1 w-full rounded-xl border-2 border-line bg-paper px-4 py-3 font-body text-xl text-ink outline-none focus:border-steel"
              />
            </label>
            {snapshot.pending_epc && (
              <p className="break-all font-mono text-xs text-steel">
                EPC {snapshot.pending_epc}
              </p>
            )}
          </div>
          <div className="grid w-full max-w-md grid-cols-1 gap-5 sm:grid-cols-2">
            <button
              disabled={submitting || !snapshot.cycle_id}
              onClick={() => void submitRegistration("register")}
              className="flex min-h-28 flex-col items-center justify-center gap-1 rounded-2xl bg-ok/15 ring-2 ring-ok/50 transition-transform active:scale-[0.98] disabled:opacity-50"
            >
              <span className="font-display text-2xl font-semibold uppercase tracking-wide">
                Hinzufügen
              </span>
              <span className="font-mono text-sm text-ok">
                → Referenz speichern
              </span>
            </button>
            <button
              disabled={submitting || !snapshot.cycle_id}
              onClick={() => void submitRegistration("dismiss")}
              className="flex min-h-28 flex-col items-center justify-center gap-1 rounded-2xl bg-paper ring-2 ring-black/10 transition-transform active:scale-[0.98] disabled:opacity-50"
            >
              <span className="font-display text-2xl font-semibold uppercase tracking-wide">
                Verwerfen
              </span>
              <span className="font-mono text-sm text-steel">
                → Zur Prüfung
              </span>
            </button>
          </div>
          {submitError && (
            <p className="font-mono text-sm text-err">{submitError}</p>
          )}
        </div>
      </Frame>
    );
  }

  if (snapshot.feedback_recorded) {
    const nothingFound = snapshot.feedback_category === "nothing_found";
    return (
      <StatusScreen
        snapshot={snapshot}
        title="Erfasst"
        detail={
          nothingFound
            ? "Keine Gegenstände. Bitte entnehmen."
            : "Fund erfasst. Bitte entnehmen."
        }
        status={nothingFound ? "ok" : "err"}
      />
    );
  }

  const garment = snapshot.garment;

  if (screen === "check") {
    return (
      <Frame status="err" snapshot={snapshot}>
        <div className="flex flex-1 flex-col items-center justify-center gap-10 px-8 text-center">
          <div>
            <GarmentHeading garment={garment} />
            <h1 className="mt-4 font-display text-8xl font-bold uppercase leading-none tracking-tight">
              Bitte prüfen
            </h1>
            <p className="mt-4 font-mono text-sm uppercase tracking-[0.2em] text-steel">
              Gegenstände in der Tasche?
            </p>
          </div>
          <div className="grid w-full max-w-4xl grid-cols-1 gap-6 sm:grid-cols-2">
            <button
              disabled={submitting || !snapshot.cycle_id}
              onClick={() => void submitFeedback("nothing_found")}
              className="flex min-h-44 flex-col items-center justify-center gap-2 rounded-2xl bg-ok/15 ring-2 ring-ok/50 transition-transform active:scale-[0.98] disabled:opacity-50"
            >
              <span className="font-display text-3xl font-semibold uppercase tracking-wide">
                Nichts gefunden
              </span>
              <span className="font-mono text-sm text-ok">
                → Rückmeldung speichern
              </span>
            </button>
            <button
              disabled={submitting || !snapshot.cycle_id}
              onClick={() => setScreen("found")}
              className="flex min-h-44 flex-col items-center justify-center gap-2 rounded-2xl bg-err/15 ring-2 ring-err/50 transition-transform active:scale-[0.98] disabled:opacity-50"
            >
              <span className="font-display text-3xl font-semibold uppercase tracking-wide">
                Etwas gefunden
              </span>
              <span className="font-mono text-sm text-err">
                → Gegenstand wählen
              </span>
            </button>
          </div>
          {submitError && (
            <p className="font-mono text-sm text-err">{submitError}</p>
          )}
        </div>
      </Frame>
    );
  }

  if (screen === "found") {
    return (
      <Frame status="err" snapshot={snapshot}>
        <div className="flex flex-1 flex-col p-8">
          <div className="mb-8 text-center">
            <GarmentHeading garment={garment} />
            <h1 className="mt-2 font-display text-6xl font-bold uppercase tracking-tight">
              Was wurde gefunden?
            </h1>
            <p className="mt-2 font-mono text-sm uppercase tracking-[0.2em] text-steel">
              Antippen zum Erfassen
            </p>
          </div>
          <div className="mx-auto grid w-full max-w-4xl grid-cols-3 gap-5">
            {FOUND_ITEMS.map((item) => (
              <button
                key={item.category}
                disabled={submitting}
                onClick={() => void submitFeedback(item.category)}
                className="flex min-h-40 flex-col items-center justify-center gap-3 rounded-2xl bg-paper ring-2 ring-black/10 transition-all active:scale-[0.97] active:ring-err disabled:opacity-50"
              >
                <span className="grid size-20 place-items-center rounded-xl bg-panel ring-1 ring-black/5">
                  <item.Icon
                    className="size-10"
                    strokeWidth={1.5}
                    aria-hidden
                  />
                </span>
                <span className="font-body text-xl font-semibold">
                  {item.label}
                </span>
              </button>
            ))}
          </div>
          {submitError && (
            <p className="mt-5 text-center font-mono text-sm text-err">
              {submitError}
            </p>
          )}
        </div>
      </Frame>
    );
  }

  if (
    snapshot.lifecycle !== "pass" ||
    garment === null ||
    snapshot.measurement === null
  ) {
    return (
      <StatusScreen
        snapshot={snapshot}
        title="Bitte prüfen"
        detail="Die Messung ist nicht vollständig. Kleidungsstück manuell prüfen."
        status="err"
      />
    );
  }

  const measurement = snapshot.measurement;
  return (
    <Frame status="ok" snapshot={snapshot}>
      <button
        onClick={() => setScreen("check")}
        className="grid flex-1 grid-cols-1 gap-px bg-line text-left md:grid-cols-2"
      >
        <div className="flex flex-col items-center justify-center bg-ok/5 p-8">
          <p className="font-mono text-sm uppercase tracking-[0.3em] text-steel">
            Schacht
          </p>
          <p className="font-display text-[220px] font-bold leading-none tracking-tighter tabular-nums">
            {garment.chute_number}
          </p>
          <div className="mt-8 w-full max-w-xs space-y-2">
            {[
              ["Soll", measurement.reference_g],
              ["Ist", measurement.measured_g],
              ["Differenz", measurement.difference_g],
            ].map(([label, value]) => (
              <div
                key={String(label)}
                className="flex items-baseline justify-between border-b border-line pb-2 last:border-0"
              >
                <span className="font-mono text-sm uppercase text-steel">
                  {label}
                </span>
                <span
                  className={cn(
                    "font-mono text-2xl tabular-nums",
                    label === "Differenz" && "font-medium text-ok",
                  )}
                >
                  {formatWeight(value as number | null)} g
                </span>
              </div>
            ))}
          </div>
        </div>
        <div className="flex flex-col justify-center bg-ok/5 p-12">
          <p className="font-display text-5xl font-bold uppercase tracking-tight">
            {garment.product_name}
          </p>
          <p className="mt-1 font-mono text-sm uppercase tracking-[0.2em] text-steel">
            Größe {garment.size}
          </p>
          <dl className="mt-10 space-y-4">
            {[
              {
                label: "Kunde",
                main: garment.customer_name,
                sub: garment.customer_number,
              },
              {
                label: "Träger",
                main: garment.wearer_name,
                sub: garment.wearer_number,
              },
              { label: "Artikelnummer", value: garment.article_number },
              { label: "ID-Nummer", value: garment.id_number },
              {
                label: "Jahr / Woche",
                value: `${garment.manufacture_year} / ${String(garment.manufacture_week).padStart(2, "0")}`,
              },
            ].map((item) => (
              <div
                key={item.label}
                className="flex items-baseline justify-between border-b border-line pb-3"
              >
                <dt className="font-mono text-sm uppercase tracking-wider text-steel">
                  {item.label}
                </dt>
                {"value" in item ? (
                  <dd className="font-mono text-2xl tabular-nums">
                    {item.value}
                  </dd>
                ) : (
                  <dd className="text-right">
                    <span className="font-display text-2xl font-normal tracking-tight">
                      {item.main}
                    </span>
                    <span className="ml-2 font-mono text-sm tabular-nums text-steel">
                      {item.sub}
                    </span>
                  </dd>
                )}
              </div>
            ))}
          </dl>
          <div className="mt-10 flex items-center gap-3">
            <span className="size-4 rounded-full bg-ok" />
            <span className="font-display text-xl font-semibold uppercase tracking-wide text-ink/80">
              Keine Gegenstände
            </span>
            <span className="ml-auto font-mono text-xs uppercase tracking-wider text-steel">
              Tippen zum Prüfen →
            </span>
          </div>
        </div>
      </button>
    </Frame>
  );
}
