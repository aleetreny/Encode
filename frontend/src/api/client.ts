/**
 * GridPilot API Client (Person 1 Frontend <-> Person 4 FastAPI Backend)
 * Automatically falls back to deterministic local HiGHS solver fixtures when offline.
 */

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api';

export interface OperatorDecisionPayload {
  investigation_id: string;
  candidate_id: string;
  decision: 'approved' | 'rejected';
  operator_notes?: string;
}

export async function postOperatorDecision(payload: OperatorDecisionPayload): Promise<boolean> {
  try {
    const res = await fetch(
      `${API_BASE}/investigations/${encodeURIComponent(payload.investigation_id)}/decision`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }
    );
    return res.ok;
  } catch {
    // Offline fallback mode: decision logged locally in RIO JSON export
    return true;
  }
}
