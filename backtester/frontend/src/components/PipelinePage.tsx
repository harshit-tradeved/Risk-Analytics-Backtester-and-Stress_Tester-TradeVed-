import { useEffect, useRef, useState } from "react";
import {
  startPipeline, getPipelineRun, submitPipelineCheckpoint,
  retryPipelineSymbol, resumePipelineRun,
} from "../api";
import type { PipelineRunState } from "../types";

const POLL_MS = 2000;

export default function PipelinePage({ userId }: { userId: string }) {
  const [transcript, setTranscript] = useState("");
  const [tweak, setTweak] = useState("");
  const [symbol, setSymbol] = useState("BTC/USDT");
  const [runId, setRunId] = useState<string | null>(null);
  const [run, setRun] = useState<PipelineRunState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [checkpointTweak, setCheckpointTweak] = useState("");
  const pollRef = useRef<number | null>(null);

  useEffect(() => {
    if (!runId) return;
    const poll = async () => {
      try {
        const state = await getPipelineRun(runId);
        setRun(state);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    };
    poll();
    pollRef.current = window.setInterval(poll, POLL_MS);
    return () => { if (pollRef.current) window.clearInterval(pollRef.current); };
  }, [runId]);

  const handleStart = async () => {
    setError(null);
    try {
      const { run_id } = await startPipeline({ user_id: userId, transcript, tweak: tweak || undefined, symbol });
      setRunId(run_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleConfirm = async () => {
    if (!runId) return;
    await submitPipelineCheckpoint(runId, "confirm");
  };

  const handleTweakSubmit = async () => {
    if (!runId || !checkpointTweak.trim()) return;
    await submitPipelineCheckpoint(runId, "tweak", checkpointTweak);
    setCheckpointTweak("");
  };

  const handleRetrySymbol = async (newSymbol: string) => {
    if (!runId) return;
    const { run_id } = await retryPipelineSymbol(runId, newSymbol);
    setRunId(run_id);
  };

  const handleResume = async () => {
    if (!runId) return;
    await resumePipelineRun(runId);
  };

  return (
    <div className="max-w-3xl mx-auto p-6 space-y-6">
      <h1 className="text-xl font-semibold">Reel → Backtest Pipeline</h1>

      {!runId && (
        <div className="space-y-3">
          <textarea
            className="w-full border rounded p-2"
            rows={6}
            placeholder="Paste a transcript describing a trading strategy..."
            value={transcript}
            onChange={(e) => setTranscript(e.target.value)}
          />
          <input
            className="w-full border rounded p-2 italic"
            placeholder='Optional: "also try this differently" — a free-text tweak'
            value={tweak}
            onChange={(e) => setTweak(e.target.value)}
          />
          <input
            className="w-full border rounded p-2"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
          />
          <button className="px-4 py-2 rounded bg-indigo-600 text-white" onClick={handleStart}>
            Run pipeline
          </button>
        </div>
      )}

      {error && <div className="text-red-600">{error}</div>}

      {run && (
        <div className="space-y-4">
          <div className="text-sm text-gray-500">Status: {run.status} — {run.stage}</div>

          {run.status === "failed" && (
            <div className="border border-red-400 rounded p-3 text-red-700">
              This run failed: {run.error_message || "Unknown error"}
            </div>
          )}

          {run.status === "interrupted" && (
            <div className="border border-amber-400 rounded p-3">
              This run was interrupted (likely a backend restart).
              <button className="ml-2 underline" onClick={handleResume}>Resume</button>
            </div>
          )}

          {run.status === "awaiting_checkpoint" && (
            <div className="border rounded p-3 space-y-2">
              {run.disclaimer && (
                <div className="border border-amber-400 bg-amber-50 rounded p-3 text-amber-800 text-sm">
                  <strong>Heads up:</strong> {run.disclaimer} We've suggested a reasonable
                  starting point below — review it, tweak anything that doesn't fit, or confirm as-is.
                </div>
              )}
              <p>Confirm this strategy, or type a change (60–100s before we auto-proceed):</p>
              <pre className="text-xs bg-gray-100 p-2 rounded">{JSON.stringify(run.ir, null, 2)}</pre>
              <button className="px-3 py-1 rounded bg-indigo-600 text-white" onClick={handleConfirm}>
                Confirm
              </button>
              <div className="flex gap-2">
                <input
                  className="flex-1 border rounded p-2"
                  placeholder="e.g. use a faster EMA crossover"
                  value={checkpointTweak}
                  onChange={(e) => setCheckpointTweak(e.target.value)}
                />
                <button className="px-3 py-1 rounded border" onClick={handleTweakSubmit}>Apply tweak</button>
              </div>
            </div>
          )}

          {run.report && (
            <div className="space-y-3">
              <p className="text-base">{run.report.verdict}</p>
              <div className="flex flex-wrap gap-2">
                {run.report.chips.map((chip) => (
                  <span
                    key={chip.id}
                    className="px-3 py-1 rounded-full border text-sm cursor-pointer"
                    onClick={() => chip.id === "retry_symbol" && handleRetrySymbol(prompt("New symbol?") || run.symbol)}
                  >
                    <span
                      className={`inline-block w-2 h-2 rounded-full mr-2 ${chip.kind === "instant" ? "bg-indigo-500" : "bg-amber-500"}`}
                    />
                    {chip.label}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
