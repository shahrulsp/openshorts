import { apiJson } from './api';

function buildProjectTitle(data) {
  if (data?.type === 'url') {
    const rawUrl = String(data.payload || '').trim();
    if (!rawUrl) return 'Imported video';
    try {
      const url = new URL(rawUrl);
      const tail = url.pathname.split('/').filter(Boolean).pop();
      return decodeURIComponent(tail || url.hostname || 'Imported video').slice(0, 255);
    } catch (_) {
      return rawUrl.slice(0, 255);
    }
  }

  const fileName = data?.payload?.name || 'Uploaded video';
  return fileName.replace(/\.[^.]+$/, '').slice(0, 255);
}

function buildWorkflowPayload(data, legacyJobId, sourceAssetId = null) {
  const payload = {
    workflow: 'clip-generator',
    source_type: data?.type || 'unknown',
    output_format: data?.outputFormat || 'auto',
    acknowledged: !!data?.acknowledged,
    legacy_job_id: legacyJobId,
  };

  if (sourceAssetId) {
    payload.source_asset_id = sourceAssetId;
  }

  if (data?.type === 'url') {
    payload.source_url = String(data.payload || '');
  } else {
    payload.source_name = data?.payload?.name || 'upload';
    payload.source_size_bytes = Number(data?.payload?.size || 0);
  }

  return payload;
}

function summarizeResult(result, legacyJobId) {
  const clips = Array.isArray(result?.clips) ? result.clips : [];
  return {
    workflow: 'clip-generator',
    legacy_job_id: legacyJobId,
    clip_count: clips.length,
    cost_analysis: result?.cost_analysis || null,
    clips: clips.map((clip, index) => ({
      index,
      title: clip?.title || null,
      score: clip?.score ?? null,
      video_url: clip?.video_url || null,
    })),
  };
}

async function postJson(path, body) {
  return apiJson(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

export async function createSaasClipProjectJob(data, legacyJobId, sourceAssetId = null) {
  return postJson('/api/saas/projects/with-job', {
    project_kind: 'clip-generator',
    job_kind: 'clip-generation',
    title: buildProjectTitle(data),
    payload: buildWorkflowPayload(data, legacyJobId, sourceAssetId),
  });
}

export async function startSaasJob(jobId) {
  return postJson(`/api/saas/jobs/${jobId}/start`, {});
}

export async function completeSaasJob(jobId, result, legacyJobId) {
  return postJson(`/api/saas/jobs/${jobId}/complete`, {
    result_payload: summarizeResult(result, legacyJobId),
  });
}

export async function failSaasJob(jobId, errorText) {
  return postJson(`/api/saas/jobs/${jobId}/fail`, {
    error_text: errorText || 'Clip generation failed',
  });
}

export async function retrySaasTrackedJob(jobId, legacyJobId, sourceAssetId = null) {
  return postJson(`/api/saas/jobs/${jobId}/retry`, {
    legacy_job_id: legacyJobId,
    source_asset_id: sourceAssetId,
  });
}
