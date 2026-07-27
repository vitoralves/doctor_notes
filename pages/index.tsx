"use client";

import Head from "next/head";
import Link from "next/link";
import { SignInButton, SignedIn, SignedOut, UserButton } from "@clerk/nextjs";

export default function Home() {
  return (
    <>
      <Head>
        <title>MediNotes Pro</title>
      </Head>
      <main className="relative min-h-screen overflow-hidden">
        <div
          className="pointer-events-none absolute inset-0 opacity-40"
          style={{
            backgroundImage:
              "linear-gradient(rgba(20,32,28,0.04) 1px, transparent 1px), linear-gradient(90deg, rgba(20,32,28,0.04) 1px, transparent 1px)",
            backgroundSize: "48px 48px",
          }}
        />

        <div className="relative mx-auto flex min-h-screen max-w-6xl flex-col px-6 py-8">
          <nav className="flex items-center justify-between animate-fade-up">
            <p className="font-[family-name:var(--font-display)] text-2xl md:text-3xl">
              MediNotes Pro
            </p>
            <div>
              <SignedOut>
                <SignInButton mode="modal">
                  <button
                    type="button"
                    className="rounded-xl bg-[var(--accent)] px-5 py-2.5 text-sm font-semibold text-white hover:bg-[var(--accent-strong)]"
                  >
                    Sign in
                  </button>
                </SignInButton>
              </SignedOut>
              <SignedIn>
                <div className="flex items-center gap-3">
                  <Link
                    href="/product/"
                    className="rounded-xl bg-[var(--accent)] px-5 py-2.5 text-sm font-semibold text-white hover:bg-[var(--accent-strong)]"
                  >
                    Open app
                  </Link>
                  <UserButton showName={true} />
                </div>
              </SignedIn>
            </div>
          </nav>

          <section className="flex flex-1 flex-col justify-center py-16 md:py-24">
            <h1 className="max-w-3xl font-[family-name:var(--font-display)] text-5xl leading-[1.05] tracking-tight md:text-7xl animate-fade-up">
              MediNotes Pro
            </h1>
            <p className="mt-5 max-w-xl text-lg text-[var(--muted)] md:text-xl animate-fade-up-delay">
              Turn consultation notes into structured summaries, next steps, and
              patient-ready emails — streamed live, saved to your history.
            </p>

            <div className="mt-8 flex flex-wrap gap-3 animate-fade-up-delay">
              <SignedOut>
                <SignInButton mode="modal">
                  <button
                    type="button"
                    className="rounded-xl bg-[var(--accent)] px-6 py-3 font-semibold text-white hover:bg-[var(--accent-strong)]"
                  >
                    Start demo
                  </button>
                </SignInButton>
              </SignedOut>
              <SignedIn>
                <Link
                  href="/product/"
                  className="rounded-xl bg-[var(--accent)] px-6 py-3 font-semibold text-white hover:bg-[var(--accent-strong)]"
                >
                  Open workspace
                </Link>
              </SignedIn>
              <a
                href="https://github.com/vitoralves/doctor_notes"
                target="_blank"
                rel="noreferrer"
                className="rounded-xl border border-[var(--line)] bg-white/70 px-6 py-3 font-semibold"
              >
                View on GitHub
              </a>
            </div>
          </section>

          <section className="border-t border-[var(--line)] py-12">
            <h2 className="font-[family-name:var(--font-display)] text-3xl">Built to show production judgment</h2>
            <p className="mt-2 max-w-2xl text-[var(--muted)]">
              Clerk auth and plan gating, FastAPI streaming on AWS Lambda, DynamoDB
              history, Upstash rate limits, S3 exports, and CloudWatch-friendly logs —
              optimized for near-zero study cost.
            </p>
          </section>

          <footer className="pb-6 text-sm text-[var(--muted)]">
            Demo / testing only — not for real PHI or clinical use. Each account is limited
            to 2 AI consultation generations.
          </footer>
        </div>
      </main>
    </>
  );
}
