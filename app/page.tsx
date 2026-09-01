"use client";

import { useState, useCallback, useEffect } from "react";
import {
  Flame,
  Copy,
  Check,
  AlertTriangle,
  Send,
  Loader2,
  Trash2,
  FileText,
  Sparkles,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface DimensionScore {
  name: string;
  score: number;
  feedback: string;
  suggestion: string;
}

interface Redline {
  original: string;
  replacement: string;
  reason: string;
}

interface AuditResult {
  persona: string;
  persona_avatar: string;
  roast: string;
  scores: DimensionScore[];
  overall_score: number;
  redlines: Redline[];
  rewritten_pitch: string;
  model_used: string;
}

interface AuditError {
  error: string;
  message: string;
  raw_text?: string;
  retry_after?: number;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PERSONAS = [
  { value: "techcrunch", label: "TechCrunch — Sarah Chen", icon: "👩‍💻" },
  { value: "forbes", label: "Forbes — Marcus Williams", icon: "📰" },
  { value: "the_verge", label: "The Verge — Priya Kapoor", icon: "📱" },
  { value: "gulf_news", label: "Gulf News — Fatima Al-Rashid", icon: "🌍" },
  { value: "roastbot", label: "RoastBot 🔥", icon: "🔥" },
] as const;

const WORD_SOFT_CAP = 300;
const WORD_HARD_CAP = 1000;
const MIN_CHARS = 50;

const BUZZWORDS = [
  "synergy",
  "game-changing",
  "revolutionary",
  "disrupt",
  "disruptive",
  "leverage",
  "cutting-edge",
  "unprecedented",
  "ecosystem",
  "world-class",
  "best-in-class",
  "innovative",
  "scalable",
  "paradigm",
  "robust",
  "turnkey",
  "bleeding edge",
  "next-generation",
  "holistic",
  "agile",
  "mission-critical",
  "thought leadership",
  "deep dive",
  "circle back",
  "move the needle",
  "low-hanging fruit",
  "bandwidth",
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function countWords(text: string): number {
  return text
    .trim()
    .split(/\s+/)
    .filter((w) => w.length > 0).length;
}

function detectBuzzwords(text: string): string[] {
  const lower = text.toLowerCase();
  return BUZZWORDS.filter((bw) => lower.includes(bw));
}

function scoreColor(score: number): string {
  if (score <= 3) return "text-red-500";
  if (score <= 5) return "text-orange-400";
  if (score <= 7) return "text-yellow-400";
  return "text-green-400";
}

function scoreBg(score: number): string {
  if (score <= 3) return "bg-red-500/20 border-red-500/40";
  if (score <= 5) return "bg-orange-500/20 border-orange-500/40";
  if (score <= 7) return "bg-yellow-500/20 border-yellow-500/40";
  return "bg-green-500/20 border-green-500/40";
}

// ---------------------------------------------------------------------------
// CopyButton
// ---------------------------------------------------------------------------

function CopyButton({ text, label }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <button
      onClick={handleCopy}
      className="inline-flex items-center gap-1.5 rounded-md bg-white/5 px-2.5 py-1 text-xs text-neutral-400 transition hover:bg-white/10 hover:text-white cursor-pointer"
      title={`Copy ${label ?? "to clipboard"}`}
    >
      {copied ? (
        <>
          <Check className="h-3 w-3 text-green-400" /> Copied
        </>
      ) : (
        <>
          <Copy className="h-3 w-3" /> Copy
        </>
      )}
    </button>
  );
}

// ---------------------------------------------------------------------------
// ScoreBar (inline mini-bar for each dimension)
// ---------------------------------------------------------------------------

function ScoreBar({ score }: { score: number }) {
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 flex-1 rounded-full bg-neutral-800">
        <div
          className="h-full rounded-full bg-accent transition-all"
          style={{ width: `${(score / 10) * 100}%` }}
        />
      </div>
      <span className={`text-xs font-mono font-bold ${scoreColor(score)}`}>
        {score}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// AuditCard (right side)
// ---------------------------------------------------------------------------

function AuditCard({ result }: { result: AuditResult }) {
  const buzzwords = detectBuzzwords(
    result.redlines.map((r) => r.original).join(" ")
  );

  return (
    <div className="flex flex-col gap-5">
      {/* Header */}
      <div className="flex items-center gap-3">
        <span className="text-3xl">{result.persona_avatar}</span>
        <div>
          <h2 className="text-lg font-bold text-white">{result.persona}</h2>
          <p className="text-xs text-neutral-500">{result.model_used}</p>
        </div>
      </div>

      {/* Rejection Score Badge */}
      <div className={`flex items-center gap-3 rounded-xl border p-4 ${scoreBg(result.overall_score)}`}>
        <Flame className={`h-8 w-8 ${scoreColor(result.overall_score)}`} />
        <div>
          <p className="text-xs uppercase tracking-wider text-neutral-400">
            Rejection Score
          </p>
          <p className={`text-3xl font-black font-mono ${scoreColor(result.overall_score)}`}>
            {result.overall_score}
            <span className="text-sm font-normal text-neutral-500">/10</span>
          </p>
        </div>
      </div>

      {/* Cynical Editor Verdict */}
      <div className="rounded-xl border border-card-border bg-card p-4">
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-neutral-400">
            Cynical Editor Verdict
          </h3>
          <CopyButton text={result.roast} label="verdict" />
        </div>
        <p className="text-sm leading-relaxed text-neutral-300 whitespace-pre-wrap">
          {result.roast}
        </p>
      </div>

      {/* Dimension Scores */}
      <div className="rounded-xl border border-card-border bg-card p-4">
        <h3 className="mb-3 text-sm font-semibold uppercase tracking-wider text-neutral-400">
          Score Breakdown
        </h3>
        <div className="flex flex-col gap-2.5">
          {result.scores.map((s) => (
            <div key={s.name}>
              <div className="mb-0.5 flex items-center justify-between">
                <span className="text-xs text-neutral-400">{s.name}</span>
              </div>
              <ScoreBar score={s.score} />
              <p className="mt-0.5 text-[11px] text-neutral-500">
                {s.feedback}
              </p>
            </div>
          ))}
        </div>
      </div>

      {/* Fluff Word Badges */}
      {result.redlines.length > 0 && (
        <div className="rounded-xl border border-card-border bg-card p-4">
          <h3 className="mb-2 text-sm font-semibold uppercase tracking-wider text-neutral-400">
            Fluff Words Flagged
          </h3>
          <div className="flex flex-wrap gap-2">
            {result.redlines.map((r, i) => (
              <span
                key={i}
                className="inline-flex items-center gap-1 rounded-full bg-red-500/10 border border-red-500/30 px-2.5 py-1 text-xs text-red-400"
              >
                <Trash2 className="h-3 w-3" />
                {r.original}
                <span className="text-neutral-600 mx-0.5">→</span>
                <span className="text-green-400">{r.replacement}</span>
              </span>
            ))}
          </div>
          {buzzwords.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {buzzwords.map((bw) => (
                <span
                  key={bw}
                  className="rounded bg-orange-500/10 px-2 py-0.5 text-[10px] font-mono text-orange-400"
                >
                  {bw}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Rewritten Pitch */}
      <div className="rounded-xl border border-green-500/30 bg-green-500/5 p-4">
        <div className="mb-2 flex items-center justify-between">
          <h3 className="flex items-center gap-1.5 text-sm font-semibold uppercase tracking-wider text-green-400">
            <Sparkles className="h-4 w-4" /> Rewritten Pitch
          </h3>
          <CopyButton text={result.rewritten_pitch} label="rewrite" />
        </div>
        <p className="text-sm leading-relaxed text-neutral-300 whitespace-pre-wrap">
          {result.rewritten_pitch}
        </p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// EmptyState (shown when no result yet)
// ---------------------------------------------------------------------------

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center h-full text-center px-8">
      <Flame className="h-16 w-16 text-accent/30 mb-4" />
      <h2 className="text-xl font-bold text-neutral-600 mb-2">
        Ready to Roast
      </h2>
      <p className="text-sm text-neutral-600 max-w-xs">
        Paste a cold PR pitch on the left, pick an editor persona, and hit
        Analyze. The AI will roast it, score it, and rewrite it for you.
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function Home() {
  const [pitch, setPitch] = useState("");
  const [persona, setPersona] = useState("techcrunch");
  const [companyName, setCompanyName] = useState("");
  const [targetPub, setTargetPub] = useState("");
  const [campaignAngle, setCampaignAngle] = useState("");
  const [result, setResult] = useState<AuditResult | null>(null);
  const [error, setError] = useState<AuditError | null>(null);
  const [loading, setLoading] = useState(false);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  const wordCount = countWords(pitch);
  const charCount = pitch.length;
  const canSubmit = mounted && charCount >= MIN_CHARS && !loading;

  const handleSubmit = useCallback(async () => {
    if (!canSubmit) return;
    setLoading(true);
    setResult(null);
    setError(null);

    try {
      const res = await fetch("/api/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          pitch_text: pitch,
          persona,
          company_name: companyName || undefined,
          target_publication: targetPub || undefined,
          campaign_angle: campaignAngle || undefined,
        }),
      });

      const data = await res.json();

      if (!res.ok) {
        setError(data as AuditError);
      } else {
        setResult(data as AuditResult);
      }
    } catch (err) {
      setError({
        error: "model_unavailable",
        message:
          err instanceof Error
            ? err.message
            : "Network error — is the backend running?",
      });
    } finally {
      setLoading(false);
    }
  }, [pitch, persona, companyName, targetPub, campaignAngle, canSubmit]);

  const handleClear = () => {
    setPitch("");
    setCompanyName("");
    setTargetPub("");
    setCampaignAngle("");
    setResult(null);
    setError(null);
  };

  return (
    <main className="flex min-h-screen flex-col">
      {/* Top bar */}
      <header className="flex items-center justify-between border-b border-card-border bg-card px-6 py-3">
        <div className="flex items-center gap-2">
          <Flame className="h-5 w-5 text-accent" />
          <span className="text-sm font-bold tracking-tight">PitchRoast</span>
        </div>
        <span className="text-[11px] text-neutral-600">
          AI-Powered Pitch Auditor
        </span>
      </header>

      {/* Split screen */}
      <div className="flex flex-1 overflow-hidden">
        {/* ---- LEFT: Form ---- */}
        <section className="flex w-full flex-col border-r border-card-border lg:w-[42%]">
          <div className="flex-1 overflow-y-auto p-6">
            {/* Persona selector */}
            <label className="mb-1 block text-xs font-semibold uppercase tracking-wider text-neutral-400">
              Editor Persona
            </label>
            <select
              value={persona}
              onChange={(e) => setPersona(e.target.value)}
              className="mb-4 w-full rounded-lg border border-card-border bg-card px-3 py-2.5 text-sm text-white outline-none focus:border-accent"
            >
              {PERSONAS.map((p) => (
                <option key={p.value} value={p.value}>
                  {p.icon} {p.label}
                </option>
              ))}
            </select>

            {/* Pitch textarea */}
            <label className="mb-1 block text-xs font-semibold uppercase tracking-wider text-neutral-400">
              Cold PR Pitch
            </label>
            <textarea
              value={pitch}
              onChange={(e) => setPitch(e.target.value)}
              placeholder="Paste your cold PR pitch here... (min 50 characters)"
              rows={12}
              className="mb-1 w-full resize-none rounded-lg border border-card-border bg-card px-3 py-3 text-sm text-white placeholder-neutral-600 outline-none focus:border-accent"
            />

            {/* Word count */}
            <div className="mb-4 flex items-center justify-between text-[11px]">
              <span
                className={
                  wordCount > WORD_SOFT_CAP
                    ? "text-yellow-400"
                    : "text-neutral-600"
                }
              >
                {wordCount.toLocaleString()} words
                {wordCount > WORD_SOFT_CAP && (
                  <span className="ml-1">
                    (soft cap {WORD_SOFT_CAP})
                  </span>
                )}
              </span>
              <span
                className={
                  charCount > WORD_HARD_CAP * 5
                    ? "text-red-400"
                    : "text-neutral-600"
                }
              >
                {charCount.toLocaleString()} / {(WORD_HARD_CAP * 5).toLocaleString()} chars
              </span>
            </div>

            {/* Optional fields */}
            <details className="mb-4 group">
              <summary className="cursor-pointer text-xs text-neutral-500 hover:text-neutral-300 select-none">
                + Optional context (company, publication, angle)
              </summary>
              <div className="mt-3 flex flex-col gap-3">
                <input
                  type="text"
                  value={companyName}
                  onChange={(e) => setCompanyName(e.target.value)}
                  placeholder="Company name"
                  maxLength={100}
                  className="rounded-lg border border-card-border bg-card px-3 py-2 text-sm text-white placeholder-neutral-600 outline-none focus:border-accent"
                />
                <input
                  type="text"
                  value={targetPub}
                  onChange={(e) => setTargetPub(e.target.value)}
                  placeholder="Target publication"
                  maxLength={100}
                  className="rounded-lg border border-card-border bg-card px-3 py-2 text-sm text-white placeholder-neutral-600 outline-none focus:border-accent"
                />
                <input
                  type="text"
                  value={campaignAngle}
                  onChange={(e) => setCampaignAngle(e.target.value)}
                  placeholder="Campaign angle"
                  maxLength={200}
                  className="rounded-lg border border-card-border bg-card px-3 py-2 text-sm text-white placeholder-neutral-600 outline-none focus:border-accent"
                />
              </div>
            </details>

            {/* Actions */}
            <div className="flex gap-2">
              <button
                onClick={handleSubmit}
                disabled={!canSubmit}
                suppressHydrationWarning
                className="flex flex-1 items-center justify-center gap-2 rounded-lg bg-accent px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-40 cursor-pointer"
              >
                {loading ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Roasting…
                  </>
                ) : (
                  <>
                    <Send className="h-4 w-4" />
                    Analyze Pitch
                  </>
                )}
              </button>
              <button
                onClick={handleClear}
                className="rounded-lg border border-card-border bg-card px-3 py-2.5 text-sm text-neutral-400 transition hover:text-white cursor-pointer"
                title="Clear form"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          </div>
        </section>

        {/* ---- RIGHT: Results ---- */}
        <section className="hidden flex-1 overflow-y-auto p-6 lg:flex">
          {loading && (
            <div className="flex flex-1 flex-col items-center justify-center">
              <div className="relative">
                <Flame className="h-14 w-14 text-accent animate-pulse" />
              </div>
              <p className="mt-4 text-sm text-neutral-500 animate-pulse">
                The editor is reading your pitch…
              </p>
            </div>
          )}

          {!loading && error && (
            <div className="flex flex-1 flex-col items-center justify-center text-center">
              <AlertTriangle className="h-12 w-12 text-red-500/60 mb-3" />
              <h3 className="text-sm font-bold text-red-400 mb-1">
                {error.error === "rate_limit"
                  ? "Rate Limited"
                  : error.error === "parse_error"
                    ? "Parse Error"
                    : "Service Unavailable"}
              </h3>
              <p className="text-xs text-neutral-500 max-w-xs">
                {error.message}
              </p>
              {error.retry_after && (
                <p className="mt-2 text-[11px] text-neutral-600">
                  Try again in {error.retry_after}s
                </p>
              )}
            </div>
          )}

          {!loading && !error && !result && <EmptyState />}

          {!loading && !error && result && <AuditCard result={result} />}
        </section>
      </div>
    </main>
  );
}
