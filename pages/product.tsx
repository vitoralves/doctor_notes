"use client";

import { FormEvent, useEffect, useState } from "react";
import { useAuth } from "@clerk/nextjs";
import DatePicker from "react-datepicker";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkBreaks from "remark-breaks";
import { fetchEventSource } from "@microsoft/fetch-event-source";
import { Protect, PricingTable, UserButton } from "@clerk/nextjs";
import Head from "next/head";
import Link from "next/link";

type VisitItem = {
  visit_id: string;
  sk: string;
  patient_name: string;
  date_of_visit: string;
  summary: string;
  notes: string;
  model?: string;
  prompt_version?: string;
  input_tokens?: number;
  output_tokens?: number;
  created_at?: string;
};

type UsageToday = {
  request_count?: number;
  input_tokens?: number;
  output_tokens?: number;
  day?: string;
};

function ConsultationWorkspace() {
  const { getToken } = useAuth();

  const [patientName, setPatientName] = useState("");
  const [visitDate, setVisitDate] = useState<Date | null>(new Date());
  const [notes, setNotes] = useState("");
  const [output, setOutput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [visits, setVisits] = useState<VisitItem[]>([]);
  const [activeVisit, setActiveVisit] = useState<VisitItem | null>(null);
  const [usage, setUsage] = useState<UsageToday | null>(null);
  const [meta, setMeta] = useState<{ model?: string; prompt_version?: string }>({});
  const [exporting, setExporting] = useState<"markdown" | "pdf" | null>(null);

  async function authHeaders(): Promise<Record<string, string>> {
    const jwt = await getToken();
    if (!jwt) throw new Error("Authentication required");
    return {
      Authorization: `Bearer ${jwt}`,
      "Content-Type": "application/json",
    };
  }

  async function refreshHistory() {
    try {
      const headers = await authHeaders();
      const [visitsRes, usageRes] = await Promise.all([
        fetch("/api/visits", { headers }),
        fetch("/api/usage", { headers }),
      ]);
      if (visitsRes.ok) {
        const data = await visitsRes.json();
        setVisits(data.visits ?? []);
      }
      if (usageRes.ok) {
        setUsage(await usageRes.json());
      }
    } catch (err) {
      console.error(err);
    }
  }

  useEffect(() => {
    void refreshHistory();
  }, []);

  function loadVisit(visit: VisitItem) {
    setActiveVisit(visit);
    setPatientName(visit.patient_name);
    setVisitDate(visit.date_of_visit ? new Date(visit.date_of_visit) : null);
    setNotes(visit.notes);
    setOutput(visit.summary);
    setMeta({ model: visit.model, prompt_version: visit.prompt_version });
    setError("");
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setOutput("");
    setError("");
    setLoading(true);
    setActiveVisit(null);

    let headers: Record<string, string>;
    try {
      headers = await authHeaders();
    } catch {
      setError("Authentication required");
      setLoading(false);
      return;
    }

    const controller = new AbortController();
    let buffer = "";

    try {
      await fetchEventSource("/api/consultation", {
        signal: controller.signal,
        method: "POST",
        headers,
        body: JSON.stringify({
          patient_name: patientName,
          date_of_visit: visitDate?.toISOString().slice(0, 10),
          notes,
        }),
        onmessage(ev) {
          if (ev.event === "meta") {
            try {
              const payload = JSON.parse(ev.data);
              setMeta({
                model: payload.model,
                prompt_version: payload.prompt_version,
              });
            } catch {
              /* ignore */
            }
            return;
          }

          if (ev.event === "error") {
            try {
              const payload = JSON.parse(ev.data);
              setError(payload.message || "Generation failed");
            } catch {
              setError("Generation failed");
            }
            return;
          }

          if (ev.event === "done") {
            try {
              const payload = JSON.parse(ev.data);
              const saved: VisitItem = {
                visit_id: payload.visit_id,
                sk: payload.sk,
                patient_name: patientName,
                date_of_visit: visitDate?.toISOString().slice(0, 10) || "",
                notes,
                summary: buffer,
                model: payload.model,
                prompt_version: payload.prompt_version,
                input_tokens: payload.input_tokens,
                output_tokens: payload.output_tokens,
                created_at: new Date().toISOString(),
              };
              setActiveVisit(saved);
              setMeta({
                model: payload.model,
                prompt_version: payload.prompt_version,
              });
              if (payload.usage_today) setUsage(payload.usage_today);
              setVisits((prev) => [saved, ...prev.filter((v) => v.sk !== saved.sk)]);
            } catch {
              /* ignore */
            }
            return;
          }

          buffer += ev.data;
          setOutput(buffer);
        },
        onclose() {
          setLoading(false);
        },
        async onopen(response) {
          if (response.ok) return;
          let message = `Request failed (${response.status})`;
          try {
            const payload = await response.json();
            if (typeof payload.detail === "string") message = payload.detail;
            else if (payload.detail?.message) message = payload.detail.message;
          } catch {
            /* ignore */
          }
          setError(message);
          setLoading(false);
          throw new Error(message);
        },
        onerror(err) {
          console.error("SSE error:", err);
          setError((prev) => prev || "Stream interrupted. Please try again.");
          controller.abort();
          setLoading(false);
          throw err;
        },
      });
    } catch {
      setLoading(false);
    }
  }

  async function handleExport(format: "markdown" | "pdf") {
    if (!activeVisit?.sk) {
      setError("Generate or open a saved visit before exporting.");
      return;
    }
    setExporting(format);
    setError("");
    try {
      const headers = await authHeaders();
      const res = await fetch("/api/exports", {
        method: "POST",
        headers,
        body: JSON.stringify({ visit_sk: activeVisit.sk, format }),
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        const message =
          typeof detail.detail === "string"
            ? detail.detail
            : detail.detail?.message || detail.error_type || "Export failed";
        const requestId = detail.request_id || res.headers.get("x-request-id");
        throw new Error(requestId ? `${message} (request_id=${requestId})` : message);
      }
      const data = await res.json();
      window.open(data.url, "_blank", "noopener,noreferrer");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Export failed");
    } finally {
      setExporting(null);
    }
  }

  async function copyOutput() {
    if (!output) return;
    await navigator.clipboard.writeText(output);
  }

  return (
    <div className="min-h-screen px-4 py-6 md:px-8">
      <header className="mx-auto mb-6 flex max-w-7xl items-center justify-between animate-fade-up">
        <div>
          <Link href="/" className="font-[family-name:var(--font-display)] text-3xl tracking-tight">
            MediNotes Pro
          </Link>
          <p className="mt-1 text-sm text-[var(--muted)]">
            Stream notes → persist visits → export securely
          </p>
        </div>
        <UserButton showName={true} />
      </header>

      <div className="mx-auto grid max-w-7xl gap-5 lg:grid-cols-[240px_1fr] animate-fade-up-delay">
        <aside className="rounded-2xl border border-[var(--line)] bg-[var(--panel)]/90 p-4 backdrop-blur">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-[var(--muted)]">
              History
            </h2>
            <button
              type="button"
              onClick={() => void refreshHistory()}
              className="text-xs text-[var(--accent)] hover:underline"
            >
              Refresh
            </button>
          </div>
          {usage && (
            <p className="mb-3 text-xs text-[var(--muted)]">
              Today: {usage.request_count ?? 0} runs ·{" "}
              {(usage.input_tokens ?? 0) + (usage.output_tokens ?? 0)} tokens
            </p>
          )}
          <ul className="max-h-[70vh] space-y-2 overflow-y-auto">
            {visits.length === 0 && (
              <li className="text-sm text-[var(--muted)]">No saved visits yet.</li>
            )}
            {visits.map((visit) => (
              <li key={visit.sk}>
                <button
                  type="button"
                  onClick={() => loadVisit(visit)}
                  className={`w-full rounded-xl px-3 py-2 text-left transition ${
                    activeVisit?.sk === visit.sk
                      ? "bg-[var(--accent)] text-white"
                      : "bg-white/70 hover:bg-white"
                  }`}
                >
                  <div className="truncate text-sm font-medium">{visit.patient_name}</div>
                  <div
                    className={`truncate text-xs ${
                      activeVisit?.sk === visit.sk ? "text-white/80" : "text-[var(--muted)]"
                    }`}
                  >
                    {visit.date_of_visit}
                  </div>
                </button>
              </li>
            ))}
          </ul>
        </aside>

        <section className="grid gap-4 xl:grid-cols-2">
          <form
            onSubmit={handleSubmit}
            className="flex flex-col rounded-2xl border border-[var(--line)] bg-[var(--panel)]/90 p-5 backdrop-blur"
          >
            <h1 className="mb-4 font-[family-name:var(--font-display)] text-3xl">
              Consultation workspace
            </h1>

            <label className="mb-1 text-sm font-medium" htmlFor="patient">
              Patient name
            </label>
            <input
              id="patient"
              required
              value={patientName}
              onChange={(e) => setPatientName(e.target.value)}
              className="mb-3 rounded-xl border border-[var(--line)] bg-white px-3 py-2 outline-none focus:border-[var(--accent)]"
              placeholder="Full name"
            />

            <label className="mb-1 text-sm font-medium" htmlFor="date">
              Date of visit
            </label>
            <DatePicker
              id="date"
              selected={visitDate}
              onChange={(d: Date | null) => setVisitDate(d)}
              dateFormat="yyyy-MM-dd"
              required
              className="mb-3 w-full rounded-xl border border-[var(--line)] bg-white px-3 py-2 outline-none focus:border-[var(--accent)]"
            />

            <label className="mb-1 text-sm font-medium" htmlFor="notes">
              Clinical notes
            </label>
            <textarea
              id="notes"
              required
              rows={14}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              className="mb-4 min-h-64 flex-1 rounded-xl border border-[var(--line)] bg-white px-3 py-2 outline-none focus:border-[var(--accent)]"
              placeholder="Chief complaint, exam findings, assessment, plan..."
            />

            <button
              type="submit"
              disabled={loading}
              className="rounded-xl bg-[var(--accent)] px-4 py-3 font-semibold text-white transition hover:bg-[var(--accent-strong)] disabled:opacity-50"
            >
              {loading ? "Generating…" : "Generate & save"}
            </button>
          </form>

          <div className="flex flex-col rounded-2xl border border-[var(--line)] bg-white/80 p-5 backdrop-blur">
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <h2 className="mr-auto font-[family-name:var(--font-display)] text-2xl">
                Live summary
              </h2>
              <button
                type="button"
                onClick={() => void copyOutput()}
                disabled={!output}
                className="rounded-lg border border-[var(--line)] px-3 py-1.5 text-sm disabled:opacity-40"
              >
                Copy
              </button>
              <button
                type="button"
                onClick={() => void handleExport("markdown")}
                disabled={!activeVisit || exporting !== null}
                className="rounded-lg border border-[var(--line)] px-3 py-1.5 text-sm disabled:opacity-40"
              >
                {exporting === "markdown" ? "Exporting…" : "Markdown"}
              </button>
              <button
                type="button"
                onClick={() => void handleExport("pdf")}
                disabled={!activeVisit || exporting !== null}
                className="rounded-lg border border-[var(--line)] px-3 py-1.5 text-sm disabled:opacity-40"
              >
                {exporting === "pdf" ? "Exporting…" : "PDF"}
              </button>
            </div>

            {(meta.model || meta.prompt_version) && (
              <p className="mb-3 text-xs text-[var(--muted)]">
                Model {meta.model ?? "—"} · Prompt {meta.prompt_version ?? "—"}
                {activeVisit?.input_tokens != null && (
                  <>
                    {" "}
                    · Tokens {activeVisit.input_tokens}/{activeVisit.output_tokens}
                  </>
                )}
              </p>
            )}

            {error && (
              <p className="mb-3 rounded-lg bg-orange-50 px-3 py-2 text-sm text-[var(--warn)]">
                {error}
              </p>
            )}

            <div
              className={`markdown-content min-h-80 flex-1 overflow-y-auto rounded-xl border border-[var(--line)] bg-[var(--panel)] p-4 ${
                loading ? "streaming-caret" : ""
              }`}
            >
              {output ? (
                <ReactMarkdown remarkPlugins={[remarkGfm, remarkBreaks]}>
                  {output}
                </ReactMarkdown>
              ) : (
                <p className="text-sm text-[var(--muted)]">
                  Generated summary, next steps, and patient email will stream here.
                </p>
              )}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}

export default function Product() {
  return (
    <>
      <Head>
        <title>MediNotes Pro — Workspace</title>
      </Head>
      <main>
        <Protect
          plan="premium_subscription"
          fallback={
            <div className="mx-auto max-w-4xl px-4 py-16">
              <div className="mb-8 flex justify-end">
                <UserButton showName={true} />
              </div>
              <header className="mb-10 text-center animate-fade-up">
                <p className="font-[family-name:var(--font-display)] text-5xl">MediNotes Pro</p>
                <h1 className="mt-3 text-2xl font-semibold">Healthcare Professional Plan</h1>
                <p className="mt-2 text-[var(--muted)]">
                  Unlock streaming summaries, visit history, and secure exports.
                </p>
              </header>
              <div className="animate-fade-up-delay">
                <PricingTable />
              </div>
            </div>
          }
        >
          <ConsultationWorkspace />
        </Protect>
      </main>
    </>
  );
}
