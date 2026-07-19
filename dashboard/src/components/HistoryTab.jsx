import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { Loader2, Download, Film, FolderOpen, Activity, Clock3, Clapperboard, ChevronRight, RefreshCw, X } from 'lucide-react';
import { apiJson } from '../lib/api';
import { useAuth } from '../contexts/AuthContext';

// The signed-in user's saved video library (stored in R2). Private, signed links.
// Videos are grouped by project (job); re-openable projects get a "reopen"
// action that restores the whole job for further editing in the Clip Generator.
export default function HistoryTab({ onReopenProject, onRetrySaasJob }) {
  const AUTO_REFRESH_BASE_MS = 3000;
  const AUTO_REFRESH_MAX_MS = 15000;
  const { billingEnabled, saasEnabled } = useAuth();
  const saasHistoryMode = saasEnabled && !billingEnabled;
  const [videos, setVideos] = useState(null);
  const [projects, setProjects] = useState({});
  const [activity, setActivity] = useState(null);
  const [selectedProjectId, setSelectedProjectId] = useState(null);
  const [projectDetail, setProjectDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState('');
  const [isAutoRefreshing, setIsAutoRefreshing] = useState(false);
  const [lastRefreshedAt, setLastRefreshedAt] = useState(null);
  const [isManualRefreshing, setIsManualRefreshing] = useState(false);
  const [refreshFeedback, setRefreshFeedback] = useState('idle');
  const [refreshWarning, setRefreshWarning] = useState('');
  const [autoRefreshFailureCount, setAutoRefreshFailureCount] = useState(0);
  const [autoRefreshRetryDelayMs, setAutoRefreshRetryDelayMs] = useState(0);
  const [retryingJobId, setRetryingJobId] = useState(null);
  const [retryError, setRetryError] = useState('');
  const [reopening, setReopening] = useState(null);
  const [reopenError, setReopenError] = useState('');
  const [error, setError] = useState('');
  const autoRefreshFailuresRef = useRef(0);
  const [liveHeartbeatNow, setLiveHeartbeatNow] = useState(() => Date.now());
  const [liveObservedAt, setLiveObservedAt] = useState(null);
  const [liveEndedAt, setLiveEndedAt] = useState(null);
  const wasProjectLiveRef = useRef(false);

  const buildActivityRows = useCallback((projectData, jobData) => {
    const jobsByProject = new Map();
    for (const job of jobData.jobs || []) {
      if (!job.project_id) continue;
      const existing = jobsByProject.get(job.project_id);
      if (!existing || new Date(job.created_at).getTime() > new Date(existing.created_at).getTime()) {
        jobsByProject.set(job.project_id, job);
      }
    }

    return (projectData.projects || []).map((project) => ({
      project,
      latestJob: jobsByProject.get(project.id) || null,
    }));
  }, []);

  const refreshActivity = useCallback(async () => {
    const [projectData, jobData] = await Promise.all([apiJson('/api/saas/projects'), apiJson('/api/saas/jobs')]);
    const nextActivity = buildActivityRows(projectData, jobData);
    setActivity(nextActivity);
    return nextActivity;
  }, [buildActivityRows]);

  const refreshProjectDetail = useCallback(async (projectId, { silent = false } = {}) => {
    if (!projectId) return null;
    if (!silent) {
      setDetailLoading(true);
      setDetailError('');
    }
    try {
      const detail = await apiJson(`/api/saas/projects/${projectId}`);
      setProjectDetail(detail);
      return detail;
    } catch (_) {
      if (!silent) {
        setProjectDetail(null);
        setDetailError('Could not load this project detail.');
      }
      return null;
    } finally {
      if (!silent) setDetailLoading(false);
    }
  }, []);

  useEffect(() => {
    setError('');
    if (saasHistoryMode) {
      setProjectDetail(null);
      setSelectedProjectId(null);
      setDetailError('');
      refreshActivity()
        .catch(() => setError('Could not load your workspace activity.'));
      return;
    }

    apiJson('/api/history')
      .then((d) => setVideos(d.videos || []))
      .catch(() => setError('Could not load your library.'));
    apiJson('/api/projects')
      .then((d) => {
        const map = {};
        for (const p of d.projects || []) map[p.job_id] = p;
        setProjects(map);
      })
      .catch(() => {});
  }, [refreshActivity, saasHistoryMode]);

  // Group videos by job, preserving the newest-first order of /api/history.
  const groups = useMemo(() => {
    const byJob = new Map();
    for (const v of videos || []) {
      const key = v.job_id || v.id;
      if (!byJob.has(key)) byJob.set(key, []);
      byJob.get(key).push(v);
    }
    return [...byJob.entries()];
  }, [videos]);

  const handleReopen = async (jobId) => {
    if (!onReopenProject || reopening) return;
    setReopening(jobId);
    setReopenError('');
    try {
      await onReopenProject(jobId);
    } catch (e) {
      setReopenError('Could not reopen this project. Please try again.');
      setReopening(null);
    }
  };

  const fmtDate = (iso) => (iso ? new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }) : '');
  const fmtDateTime = (iso) => (
    iso
      ? new Date(iso).toLocaleString(undefined, {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
      })
      : ''
  );
  const fmtClockTime = (value) => (
    value
      ? new Date(value).toLocaleTimeString(undefined, {
        hour: 'numeric',
        minute: '2-digit',
        second: '2-digit',
      })
      : ''
  );
  const fmtElapsedShort = (milliseconds) => {
    const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
    if (totalSeconds < 60) return `${totalSeconds}s`;
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    if (minutes < 60) return `${minutes}m ${String(seconds).padStart(2, '0')}s`;
    const hours = Math.floor(minutes / 60);
    const remainingMinutes = minutes % 60;
    return `${hours}h ${String(remainingMinutes).padStart(2, '0')}m`;
  };
  const resetAutoRefreshRecovery = useCallback(() => {
    autoRefreshFailuresRef.current = 0;
    setAutoRefreshFailureCount(0);
    setAutoRefreshRetryDelayMs(0);
  }, []);
  const nextAutoRefreshDelay = useCallback((failureCount) => (
    Math.min(AUTO_REFRESH_BASE_MS * (failureCount + 1), AUTO_REFRESH_MAX_MS)
  ), [AUTO_REFRESH_BASE_MS, AUTO_REFRESH_MAX_MS]);
  const describeRefreshFallback = (reason, { failureCount = 0, retryDelayMs = 0 } = {}) => {
    const lastGood = lastRefreshedAt ? fmtClockTime(lastRefreshedAt) : '';
    const suffix = lastGood ? ` Last good detail: ${lastGood}.` : '';
    if (reason === 'manual') return `Refresh missed. Showing the last saved detail.${suffix} Try again.`;
    const retryHint = retryDelayMs ? ` Retrying in about ${Math.ceil(retryDelayMs / 1000)}s.` : '';
    if (failureCount > 1) return `Still reconnecting. Showing the last saved detail.${suffix}${retryHint}`;
    return `Connection dipped. Showing the last saved detail.${suffix}${retryHint}`;
  };
  const statusTone = (status) => {
    if (status === 'completed') return 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30';
    if (status === 'failed') return 'bg-rose-500/10 text-rose-300 border-rose-500/30';
    if (status === 'processing') return 'bg-brass/10 text-brass border-brass/30';
    return 'bg-paper3 text-ink2 border-rule';
  };
  const activityRows = activity || [];
  const detailJobs = projectDetail?.jobs || [];
  const projectIsLive = projectDetail?.project?.status === 'queued'
    || projectDetail?.project?.status === 'processing'
    || detailJobs.some((job) => job.status === 'queued' || job.status === 'processing');

  const loadProjectDetail = async (projectId) => {
    if (!projectId) return;
    setSelectedProjectId(projectId);
    setRetryError('');
    setRefreshWarning('');
    resetAutoRefreshRecovery();
    const detail = await refreshProjectDetail(projectId);
    if (detail) setLastRefreshedAt(Date.now());
  };

  const closeProjectDetail = () => {
    setSelectedProjectId(null);
    setProjectDetail(null);
    setDetailError('');
    setDetailLoading(false);
    setRefreshFeedback('idle');
    setRefreshWarning('');
    resetAutoRefreshRecovery();
    setLiveObservedAt(null);
    setLiveEndedAt(null);
    wasProjectLiveRef.current = false;
    setRetryingJobId(null);
    setRetryError('');
  };

  const fmtJson = (value) => JSON.stringify(value || {}, null, 2);
  const resultClipCount = (job) => Number(
    job?.result?.clip_count ?? (Array.isArray(job?.result?.clips) ? job.result.clips.length : 0),
  );
  const getRetryReadiness = (job) => {
    const payload = job?.payload || {};
    if (job?.status !== 'failed') {
      return {
        canRetry: false,
        label: 'available on failure',
        tone: 'bg-paper3 text-ink2 border-rule',
        sourceLabel: payload.source_type === 'url' ? 'URL source' : payload.source_type === 'file' ? 'upload source' : 'workflow source',
        help: 'Retry becomes available if this run fails.',
      };
    }

    if (payload.source_type === 'url' && payload.source_url) {
      return {
        canRetry: !!onRetrySaasJob,
        label: 'retry-ready',
        tone: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30',
        sourceLabel: 'URL source saved',
        help: 'The original URL is saved, so this failed run can restart directly.',
      };
    }

    if (payload.source_type === 'file' && payload.source_asset_id) {
      return {
        canRetry: !!onRetrySaasJob,
        label: 'retry-ready',
        tone: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30',
        sourceLabel: 'Persisted upload saved',
        help: 'A durable SaaS upload asset is available for this failed run.',
      };
    }

    if (payload.source_type === 'file' && payload.legacy_job_id) {
      return {
        canRetry: false,
        label: 're-upload needed',
        tone: 'bg-brass/10 text-brass border-brass/30',
        sourceLabel: 'Legacy temp upload only',
        help: 'This older run predates durable upload storage. Re-upload the source file to start a fresh run.',
      };
    }

    return {
      canRetry: false,
      label: 'missing source',
      tone: 'bg-rose-500/10 text-rose-300 border-rose-500/30',
      sourceLabel: 'No saved source',
      help: 'This run does not have enough saved source data to retry automatically.',
    };
  };

  const canRetryJob = (job) => getRetryReadiness(job).canRetry;

  const handleRetryJob = async (projectId, job) => {
    if (!canRetryJob(job)) return;
    setRetryingJobId(job.id);
    setRetryError('');
    try {
      await onRetrySaasJob({ projectId, job });
    } catch (e) {
      setRetryError(e?.message || 'Could not retry this job.');
      setRetryingJobId(null);
    }
  };

  const handleManualRefresh = async () => {
    if (!selectedProjectId || isManualRefreshing) return;
    setIsManualRefreshing(true);
    setDetailError('');
    setRefreshWarning('');
    try {
      const [activityResult, detailResult] = await Promise.allSettled([
        refreshActivity(),
        refreshProjectDetail(selectedProjectId, { silent: true }),
      ]);
      const detail = detailResult.status === 'fulfilled' ? detailResult.value : null;
      const refreshed = activityResult.status === 'fulfilled' && detail;

      if (refreshed) {
        setLastRefreshedAt(Date.now());
        setRefreshFeedback('success');
        setRefreshWarning('');
        resetAutoRefreshRecovery();
      } else if (projectDetail) {
        setRefreshFeedback('idle');
        setRefreshWarning(describeRefreshFallback('manual'));
      } else {
        setDetailError('Could not refresh this project detail right now.');
      }
    } catch (_) {
      if (projectDetail) {
        setRefreshFeedback('idle');
        setRefreshWarning(describeRefreshFallback('manual'));
      } else {
        setDetailError('Could not refresh this project detail right now.');
      }
    } finally {
      setIsManualRefreshing(false);
    }
  };

  useEffect(() => {
    if (refreshFeedback !== 'success' && refreshFeedback !== 'recovered') return undefined;
    const timeout = setTimeout(() => setRefreshFeedback('idle'), 2500);
    return () => clearTimeout(timeout);
  }, [refreshFeedback]);

  useEffect(() => {
    if (!saasHistoryMode || !selectedProjectId) return undefined;

    if (!projectIsLive && !retryingJobId) {
      setIsAutoRefreshing(false);
      resetAutoRefreshRecovery();
      return undefined;
    }

    setIsAutoRefreshing(true);

    let cancelled = false;
    let timeoutId;
    const scheduleRefresh = (delayMs) => {
      timeoutId = setTimeout(async () => {
        if (cancelled) return;
        try {
          const [nextActivity, detail] = await Promise.all([
            refreshActivity(),
            refreshProjectDetail(selectedProjectId, { silent: true }),
          ]);

          if (cancelled) return;
          const recoveredAfterFailure = autoRefreshFailuresRef.current > 0;
          resetAutoRefreshRecovery();
          setIsAutoRefreshing(true);
          setLastRefreshedAt(Date.now());
          setRefreshWarning('');
          if (recoveredAfterFailure) setRefreshFeedback('recovered');

          const selectedRow = nextActivity.find((row) => row.project.id === selectedProjectId);
          if (selectedRow?.latestJob && retryingJobId) {
            const stillRetrying = detail?.jobs?.some((job) => job.id === retryingJobId && job.status === 'failed');
            if (!stillRetrying) setRetryingJobId(null);
          }

          scheduleRefresh(AUTO_REFRESH_BASE_MS);
        } catch (_) {
          if (cancelled) return;
          const nextFailureCount = autoRefreshFailuresRef.current + 1;
          const nextDelay = nextAutoRefreshDelay(nextFailureCount);
          autoRefreshFailuresRef.current = nextFailureCount;
          setAutoRefreshFailureCount(nextFailureCount);
          setAutoRefreshRetryDelayMs(nextDelay);
          setIsAutoRefreshing(false);
          if (projectDetail) {
            setRefreshWarning(describeRefreshFallback('auto', {
              failureCount: nextFailureCount,
              retryDelayMs: nextDelay,
            }));
          }
          scheduleRefresh(nextDelay);
        }
      }, delayMs);
    };

    scheduleRefresh(AUTO_REFRESH_BASE_MS);

    return () => {
      cancelled = true;
      setIsAutoRefreshing(false);
      clearTimeout(timeoutId);
    };
  }, [
    AUTO_REFRESH_BASE_MS,
    detailJobs,
    nextAutoRefreshDelay,
    projectDetail,
    refreshActivity,
    refreshProjectDetail,
    resetAutoRefreshRecovery,
    retryingJobId,
    saasHistoryMode,
    selectedProjectId,
  ]);

  useEffect(() => {
    if ((!projectIsLive && !liveEndedAt) || autoRefreshFailureCount > 0) return undefined;
    setLiveHeartbeatNow(Date.now());
    const interval = setInterval(() => setLiveHeartbeatNow(Date.now()), 1000);
    return () => clearInterval(interval);
  }, [autoRefreshFailureCount, liveEndedAt, projectIsLive]);

  useEffect(() => {
    if (!selectedProjectId || !projectIsLive) {
      setLiveObservedAt(null);
      return;
    }
    setLiveObservedAt((current) => current || Date.now());
  }, [projectIsLive, selectedProjectId]);

  useEffect(() => {
    if (!selectedProjectId) {
      wasProjectLiveRef.current = false;
      setLiveEndedAt(null);
      return;
    }

    if (projectIsLive) {
      wasProjectLiveRef.current = true;
      setLiveEndedAt(null);
      return;
    }

    if (wasProjectLiveRef.current) {
      wasProjectLiveRef.current = false;
      setLiveEndedAt(Date.now());
      setLiveObservedAt(null);
    }
  }, [projectIsLive, selectedProjectId]);

  useEffect(() => {
    if (!liveEndedAt) return undefined;
    const timeout = setTimeout(() => setLiveEndedAt(null), 4000);
    return () => clearTimeout(timeout);
  }, [liveEndedAt]);

  if (((saasHistoryMode && activity === null) || (!saasHistoryMode && videos === null)) && !error) {
    return <div className="flex justify-center py-20"><Loader2 className="animate-spin text-brass" /></div>;
  }

  return (
    <div className="h-full overflow-y-auto p-8 max-w-5xl mx-auto animate-fade">
      <p className="eyebrow mb-1.5">06 · HISTORY</p>
      <h1 className="font-display lowercase text-2xl text-ink mb-2">{saasHistoryMode ? 'Workspace activity' : 'Your library'}</h1>
      <p className="text-muted text-sm mb-8 lowercase">
        {saasHistoryMode
          ? 'Track your local SaaS workspace runs, latest job state, and generated clip counts in one place.'
          : "All the shorts you've generated, saved while your plan is active. Kept for 7 days after your plan ends. Reopen a project to keep editing its clips."}
      </p>

      {error && <p className="text-danger text-sm">{error}</p>}
      {reopenError && <p className="text-danger text-sm mb-4">{reopenError}</p>}

      {saasHistoryMode && activityRows.length === 0 && (
        <div className="text-center py-20 text-muted">
          <Activity size={40} className="mx-auto mb-4 text-muted" />
          <p className="lowercase">No workspace activity yet. Run your first Clip Generator job to populate this history.</p>
        </div>
      )}

      {!saasHistoryMode && videos && videos.length === 0 && (
        <div className="text-center py-20 text-muted">
          <Film size={40} className="mx-auto mb-4 text-muted" />
          <p className="lowercase">No videos yet. Generate your first short from the Clip Generator.</p>
        </div>
      )}

      {saasHistoryMode ? (
        <div className="grid xl:grid-cols-[minmax(0,1.3fr)_minmax(320px,0.9fr)] gap-5 items-start">
          <div className="grid gap-4">
            {activityRows.map(({ project, latestJob }) => {
              const result = latestJob?.result || {};
              const clipCount = Number(
                result.clip_count ?? (Array.isArray(result.clips) ? result.clips.length : 0),
              );
              const sourceLabel = latestJob?.payload?.source_name || latestJob?.payload?.source_url || 'Local workflow';
              const isSelected = selectedProjectId === project.id;

              return (
                <article
                  key={project.id}
                  className={`card p-5 space-y-4 transition-colors ${isSelected ? 'border-brass/50 bg-paper2' : ''}`}
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-sm text-ink font-medium truncate" title={project.title || project.kind}>
                        {project.title || 'Untitled project'}
                      </p>
                      <p className="readout mt-1">
                        {fmtDateTime(project.created_at)} · {project.kind}
                      </p>
                    </div>
                    <span className={`text-micro uppercase tracking-[0.2em] border rounded-full px-2.5 py-1 ${statusTone(latestJob?.status || project.status)}`}>
                      {latestJob?.status || project.status}
                    </span>
                  </div>

                  <div className="grid sm:grid-cols-3 gap-3 text-sm">
                    <div className="rounded-input border border-rule bg-paper2 p-3">
                      <p className="eyebrow mb-1.5">LATEST JOB</p>
                      <p className="text-ink">{latestJob?.kind || 'No jobs yet'}</p>
                      <p className="text-muted text-xs mt-1">{latestJob ? `Attempts: ${latestJob.attempts}` : 'Waiting for first job'}</p>
                    </div>
                    <div className="rounded-input border border-rule bg-paper2 p-3">
                      <p className="eyebrow mb-1.5">SOURCE</p>
                      <p className="text-ink line-clamp-2 break-all">{sourceLabel}</p>
                      <p className="text-muted text-xs mt-1">{latestJob?.payload?.source_type || 'workflow'}</p>
                    </div>
                    <div className="rounded-input border border-rule bg-paper2 p-3">
                      <p className="eyebrow mb-1.5">OUTPUT</p>
                      <p className="text-ink flex items-center gap-2"><Clapperboard size={14} className="text-brass" /> {clipCount} clip{clipCount === 1 ? '' : 's'}</p>
                      <p className="text-muted text-xs mt-1">{latestJob?.finished_at ? `Finished ${fmtDateTime(latestJob.finished_at)}` : latestJob?.started_at ? `Started ${fmtDateTime(latestJob.started_at)}` : 'Queued locally'}</p>
                    </div>
                  </div>

                  {latestJob?.error_text && (
                    <div className="rounded-input border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
                      {latestJob.error_text}
                    </div>
                  )}

                  <div className="flex flex-wrap items-center justify-between gap-3 text-xs text-muted">
                    <div className="flex flex-wrap items-center gap-4">
                      <span className="inline-flex items-center gap-1.5"><Clock3 size={13} /> progress {latestJob?.progress ?? 0}%</span>
                      {latestJob?.payload?.legacy_job_id && <span>legacy job {latestJob.payload.legacy_job_id}</span>}
                    </div>
                    <button
                      onClick={() => loadProjectDetail(project.id)}
                      className="btn-ghost px-3 py-2 text-xs shrink-0"
                    >
                      view details <ChevronRight size={14} />
                    </button>
                  </div>
                </article>
              );
            })}
          </div>

          <aside className="card p-5 xl:sticky xl:top-8 min-h-[240px]">
            <div className="flex items-start justify-between gap-3 mb-4">
              <div>
                <p className="eyebrow mb-1.5">PROJECT DETAIL</p>
                <h2 className="font-display lowercase text-xl text-ink">
                  {projectDetail?.project?.title || 'Select a project'}
                </h2>
                <p className="text-muted text-sm mt-1 lowercase">
                  {projectDetail?.project
                    ? `${projectDetail.project.kind} · created ${fmtDateTime(projectDetail.project.created_at)}`
                    : 'Choose a workspace activity card to inspect its job timeline and outputs.'}
                </p>
                {projectDetail && (
                  <div className="flex flex-wrap items-center gap-2 mt-3 text-xs">
                    <span className={`inline-flex items-center gap-1.5 border rounded-full px-2.5 py-1 ${
                      autoRefreshFailureCount > 0
                        ? 'bg-brass/10 text-brass border-brass/30'
                        : refreshFeedback === 'recovered'
                          ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30'
                          : isAutoRefreshing
                            ? 'bg-brass/10 text-brass border-brass/30'
                            : 'bg-paper3 text-ink2 border-rule'
                    }`}>
                      <span className={`h-1.5 w-1.5 rounded-full ${
                        autoRefreshFailureCount > 0
                          ? 'bg-brass animate-pulse'
                          : refreshFeedback === 'recovered'
                            ? 'bg-emerald-300'
                            : isAutoRefreshing
                              ? 'bg-brass animate-pulse'
                              : 'bg-ink2/60'
                      }`} />
                      {autoRefreshFailureCount > 0
                        ? 'reconnecting'
                        : refreshFeedback === 'recovered'
                          ? 'reconnected'
                          : isAutoRefreshing
                            ? 'live refresh on'
                            : 'snapshot stable'}
                    </span>
                    {lastRefreshedAt && (
                      <span className="text-muted">
                        {autoRefreshFailureCount > 0 && autoRefreshRetryDelayMs > 0
                          ? `retrying in about ${Math.ceil(autoRefreshRetryDelayMs / 1000)}s`
                          : refreshFeedback === 'recovered'
                            ? `reconnected at ${fmtClockTime(lastRefreshedAt)}`
                          : projectIsLive && liveObservedAt
                            ? `live for ${fmtElapsedShort(liveHeartbeatNow - liveObservedAt)}`
                            : projectIsLive
                              ? 'live now'
                          : liveEndedAt
                            ? `live ended ${fmtElapsedShort(liveHeartbeatNow - liveEndedAt)} ago`
                          : refreshFeedback === 'success'
                            ? `just refreshed at ${fmtClockTime(lastRefreshedAt)}`
                            : `last updated ${fmtClockTime(lastRefreshedAt)}`}
                      </span>
                    )}
                  </div>
                )}
              </div>
              {selectedProjectId && (
                <div className="flex items-center gap-2 shrink-0">
                  <button
                    onClick={handleManualRefresh}
                    disabled={isManualRefreshing}
                    className="btn-ghost px-3 py-2 text-xs"
                  >
                    {isManualRefreshing
                      ? <><Loader2 size={14} className="animate-spin" /> refreshing…</>
                      : <><RefreshCw size={14} /> refresh now</>}
                  </button>
                  <button onClick={closeProjectDetail} className="btn-quiet px-3 py-2 text-xs">
                    <X size={14} /> close
                  </button>
                </div>
              )}
            </div>

            {detailLoading && (
              <div className="flex justify-center py-14"><Loader2 className="animate-spin text-brass" /></div>
            )}

            {!detailLoading && detailError && (
              <div className="rounded-input border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
                {detailError}
              </div>
            )}

            {!detailLoading && !detailError && !projectDetail && (
              <div className="text-sm text-muted py-12 lowercase">
                No project selected yet.
              </div>
            )}

            {!detailLoading && !detailError && projectDetail && (
              <div className="space-y-4">
                {retryError && (
                  <div className="rounded-input border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
                    {retryError}
                  </div>
                )}
                {refreshWarning && (
                  <div className="rounded-input border border-brass/30 bg-brass/10 px-3 py-2 text-sm text-brass">
                    {refreshWarning}
                  </div>
                )}
                <div className="grid sm:grid-cols-2 gap-3 text-sm">
                  <div className="rounded-input border border-rule bg-paper2 p-3">
                    <p className="eyebrow mb-1.5">STATUS</p>
                    <p className="text-ink capitalize">{projectDetail.project.status}</p>
                  </div>
                  <div className="rounded-input border border-rule bg-paper2 p-3">
                    <p className="eyebrow mb-1.5">JOBS</p>
                    <p className="text-ink">{detailJobs.length}</p>
                  </div>
                </div>

                <div className="space-y-3">
                  {detailJobs.map((job) => {
                    const retryReadiness = getRetryReadiness(job);

                    return (
                    <section key={job.id} className="rounded-card border border-rule bg-paper2 p-4 space-y-3">
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <div>
                          <p className="text-sm text-ink font-medium">{job.kind}</p>
                          <p className="readout mt-1">{fmtDateTime(job.created_at)}</p>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className={`text-micro uppercase tracking-[0.2em] border rounded-full px-2.5 py-1 ${statusTone(job.status)}`}>
                            {job.status}
                          </span>
                          <button
                            onClick={() => handleRetryJob(projectDetail.project.id, job)}
                            disabled={!canRetryJob(job) || retryingJobId === job.id}
                            className={`btn-ghost px-3 py-2 text-xs ${!canRetryJob(job) ? 'opacity-50 cursor-not-allowed' : ''}`}
                            title={retryReadiness.help}
                          >
                            {retryingJobId === job.id
                              ? <><Loader2 size={14} className="animate-spin" /> retrying…</>
                              : 'Retry'}
                          </button>
                        </div>
                      </div>

                      <div className="grid sm:grid-cols-3 gap-3 text-xs text-muted">
                        <div>attempts {job.attempts}</div>
                        <div>progress {job.progress}%</div>
                        <div>{job.finished_at ? `finished ${fmtDateTime(job.finished_at)}` : job.started_at ? `started ${fmtDateTime(job.started_at)}` : 'queued locally'}</div>
                      </div>

                      <div className="grid sm:grid-cols-2 gap-3 text-sm">
                        <div className="rounded-input border border-rule bg-paper3 p-3">
                          <p className="eyebrow mb-1.5">SOURCE READINESS</p>
                          <p className="text-ink">{retryReadiness.sourceLabel}</p>
                          <p className="text-muted text-xs mt-1">{job.payload?.source_name || job.payload?.source_url || 'Local workflow payload'}</p>
                        </div>
                        <div className="rounded-input border border-rule bg-paper3 p-3">
                          <p className="eyebrow mb-1.5">RETRY STATE</p>
                          <div className="flex items-center gap-2 mb-2">
                            <span className={`text-micro uppercase tracking-[0.2em] border rounded-full px-2.5 py-1 ${retryReadiness.tone}`}>
                              {retryReadiness.label}
                            </span>
                          </div>
                          <p className="text-muted text-xs">{retryReadiness.help}</p>
                        </div>
                      </div>

                      {job.error_text && (
                        <div className="rounded-input border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
                          {job.error_text}
                        </div>
                      )}

                      <div className="grid gap-3">
                        <div>
                          <p className="eyebrow mb-1.5">PAYLOAD</p>
                          <pre className="text-xs text-ink2 bg-black/30 border border-rule rounded-input p-3 overflow-x-auto whitespace-pre-wrap break-all">{fmtJson(job.payload)}</pre>
                        </div>
                        <div>
                          <p className="eyebrow mb-1.5">RESULT</p>
                          <div className="text-xs text-muted mb-2 lowercase">
                            {resultClipCount(job)} clip{resultClipCount(job) === 1 ? '' : 's'}
                          </div>
                          <pre className="text-xs text-ink2 bg-black/30 border border-rule rounded-input p-3 overflow-x-auto whitespace-pre-wrap break-all">{fmtJson(job.result)}</pre>
                        </div>
                      </div>
                    </section>
                    );
                  })}
                </div>
              </div>
            )}
          </aside>
        </div>
      ) : (
        <div className="space-y-10">
          {groups.map(([jobId, vids]) => {
            const project = projects[jobId];
            return (
              <section key={jobId}>
                <div className="flex flex-wrap items-center justify-between gap-3 mb-4 pb-2 border-b border-rule">
                  <div className="min-w-0">
                    <p className="text-sm text-ink font-medium truncate" title={project?.title || vids[0]?.title}>
                      {project?.title || vids[0]?.title || 'Project'}
                    </p>
                    <p className="readout mt-0.5">
                      {fmtDate(vids[0]?.created_at)} · {vids.length} clip{vids.length === 1 ? '' : 's'}
                    </p>
                  </div>
                  {project && onReopenProject && (
                    <button
                      onClick={() => handleReopen(jobId)}
                      disabled={!!reopening}
                      className="btn-ghost px-3 py-2 text-xs shrink-0"
                      title="Restore this project in the Clip Generator to keep editing subtitles, hooks, effects and dubbing"
                    >
                      {reopening === jobId
                        ? <><Loader2 size={14} className="animate-spin" /> reopening…</>
                        : <><FolderOpen size={14} /> reopen project</>}
                    </button>
                  )}
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-5">
                  {vids.map((v) => (
                    <div key={v.id} className="card card-hover overflow-hidden group">
                      <div className="aspect-[9/16] bg-black">
                        <video src={v.view_url} controls preload="metadata" className="w-full h-full object-contain" />
                      </div>
                      <div className="p-3">
                        <p className="text-sm text-ink font-medium line-clamp-2 mb-1" title={v.title}>{v.title || 'Short'}</p>
                        <div className="flex items-center justify-between">
                          <span className="readout">{fmtDate(v.created_at)}</span>
                          <a href={v.download_url} className="text-micro font-mono uppercase text-brass hover:text-ink flex items-center gap-1 transition-colors" title="Download">
                            <Download size={14} /> Download
                          </a>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}
