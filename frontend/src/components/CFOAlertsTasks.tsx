import React, { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle,
  Brain,
  CheckCircle,
  Clock,
  ListChecks,
  Plus,
  RefreshCw,
  ShieldCheck,
  X,
  type LucideIcon,
} from 'lucide-react';
import apiService from '../services/api';

interface Alert {
  id: number;
  title: string;
  message: string;
  severity: 'critical' | 'warning' | 'info';
  status: 'active' | 'acknowledged' | 'dismissed';
  created_at: string;
}

interface Task {
  id: number;
  title: string;
  status: 'open' | 'in_progress' | 'done';
  due_date?: string;
  entity_type?: string;
  entity_id?: number;
}

interface Recommendation {
  id: string;
  insight_id: number;
  category: string;
  severity: 'critical' | 'high' | 'medium' | 'low' | 'info';
  priority_score: number;
  title: string;
  rationale?: string;
  recommended_action?: string;
  next_steps: string[];
  source_systems: string[];
  confidence: 'high' | 'medium' | 'low';
  route: string;
  disclaimer: string;
  updated_at?: string;
}

interface RecommendationsResponse {
  count: number;
  disclaimer: string;
  recommendations: Recommendation[];
  summary: {
    critical: number;
    high: number;
    top_recommendation_title?: string;
  };
}

interface Props {
  darkMode: boolean;
}

const severityClasses: Record<string, string> = {
  critical: 'border-red-500 bg-red-50 text-red-900',
  high: 'border-orange-500 bg-orange-50 text-orange-900',
  medium: 'border-yellow-500 bg-yellow-50 text-yellow-900',
  low: 'border-blue-500 bg-blue-50 text-blue-900',
  info: 'border-sky-500 bg-sky-50 text-sky-900',
  warning: 'border-yellow-500 bg-yellow-50 text-yellow-900',
};

const statusColor = (status: string) => {
  switch (status) {
    case 'done': return 'text-green-600';
    case 'in_progress': return 'text-blue-600';
    default: return 'text-gray-500';
  }
};

const CFOAlertsTasks: React.FC<Props> = ({ darkMode }) => {
  const [activeTab, setActiveTab] = useState<'recommendations' | 'alerts' | 'tasks'>('recommendations');
  const [showNewTask, setShowNewTask] = useState(false);
  const [newTaskTitle, setNewTaskTitle] = useState('');
  const queryClient = useQueryClient();

  const panelClass = `p-5 rounded-lg border ${
    darkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
  }`;
  const mutedText = darkMode ? 'text-gray-400' : 'text-gray-600';

  const { data: recommendations, isFetching: loadingRecommendations } = useQuery<RecommendationsResponse>({
    queryKey: ['financial-recommendations'],
    queryFn: () => apiService.get('/brain/recommendations?status=active&limit=30'),
  });

  const { data: alerts } = useQuery<Alert[]>({
    queryKey: ['alerts'],
    queryFn: () => apiService.get('/alerts'),
  });

  const { data: tasks } = useQuery<Task[]>({
    queryKey: ['tasks'],
    queryFn: () => apiService.get('/tasks'),
  });

  const refreshRecommendations = useMutation({
    mutationFn: () => apiService.get('/brain/recommendations?status=active&limit=30&refresh=true'),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['financial-recommendations'] });
      queryClient.invalidateQueries({ queryKey: ['tasks'] });
    },
  });

  const updateInsight = useMutation({
    mutationFn: ({ id, status }: { id: number; status: string }) =>
      apiService.patch(`/brain/insights/${id}`, { status }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['financial-recommendations'] }),
  });

  const dismissAlert = useMutation({
    mutationFn: (id: number) => apiService.patch(`/alerts/${id}`, { status: 'dismissed' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['alerts'] }),
  });

  const acknowledgeAlert = useMutation({
    mutationFn: (id: number) => apiService.patch(`/alerts/${id}`, { status: 'acknowledged' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['alerts'] }),
  });

  const updateTask = useMutation({
    mutationFn: ({ id, status }: { id: number; status: string }) =>
      apiService.patch(`/tasks/${id}`, { status }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['tasks'] }),
  });

  const createTask = useMutation({
    mutationFn: (title: string) => apiService.post('/tasks', { title }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] });
      setNewTaskTitle('');
      setShowNewTask(false);
    },
  });

  const alertList = alerts || [];
  const taskList = tasks || [];
  const recommendationList = recommendations?.recommendations || [];

  const tabButton = (
    id: 'recommendations' | 'alerts' | 'tasks',
    label: string,
    count: number,
    Icon: LucideIcon,
  ) => (
    <button
      type="button"
      onClick={() => setActiveTab(id)}
      className={`inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition ${
        activeTab === id
          ? 'bg-blue-600 text-white'
          : darkMode ? 'bg-gray-700 text-gray-200 hover:bg-gray-600' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
      }`}
    >
      <Icon size={16} />
      <span>{label}</span>
      <span className="rounded bg-black/10 px-1.5 py-0.5 text-xs">{count}</span>
    </button>
  );

  return (
    <div dir="rtl" className={`p-6 space-y-5 ${darkMode ? 'text-white' : 'text-gray-900'}`}>
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <h1 className="text-2xl font-bold">מרכז החלטות פיננסיות</h1>
          <p className={`mt-1 text-sm ${mutedText}`}>
            המלצות תפעוליות מתוך SUMIT, Open Finance, תקציב, התאמות בנק ונתוני AR/AP.
          </p>
        </div>
        <button
          type="button"
          onClick={() => refreshRecommendations.mutate()}
          disabled={refreshRecommendations.isPending || loadingRecommendations}
          className="inline-flex items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
        >
          <RefreshCw size={16} className={refreshRecommendations.isPending ? 'animate-spin' : ''} />
          רענן המלצות
        </button>
      </div>

      <div className={panelClass}>
        <div className="grid gap-3 md:grid-cols-4">
          <div>
            <p className={`text-xs ${mutedText}`}>המלצות פעילות</p>
            <p className="mt-1 text-2xl font-bold">{recommendations?.count || 0}</p>
          </div>
          <div>
            <p className={`text-xs ${mutedText}`}>קריטיות</p>
            <p className="mt-1 text-2xl font-bold text-red-600">{recommendations?.summary.critical || 0}</p>
          </div>
          <div>
            <p className={`text-xs ${mutedText}`}>גבוהות</p>
            <p className="mt-1 text-2xl font-bold text-orange-600">{recommendations?.summary.high || 0}</p>
          </div>
          <div className="flex items-start gap-2">
            <ShieldCheck size={18} className="mt-0.5 text-green-600" />
            <p className={`text-xs leading-5 ${mutedText}`}>{recommendations?.disclaimer}</p>
          </div>
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        {tabButton('recommendations', 'המלצות', recommendationList.length, Brain)}
        {tabButton('alerts', 'התראות', alertList.filter((a) => a.status === 'active').length, AlertTriangle)}
        {tabButton('tasks', 'משימות', taskList.filter((t) => t.status !== 'done').length, ListChecks)}
      </div>

      {activeTab === 'recommendations' && (
        <div className="space-y-3">
          {recommendationList.length === 0 ? (
            <div className={panelClass}>
              <div className={`py-10 text-center ${mutedText}`}>
                <CheckCircle size={42} className="mx-auto mb-3 opacity-60" />
                <p>אין כרגע המלצות פעילות. אפשר להריץ רענון כדי לבדוק את הנתונים מחדש.</p>
              </div>
            </div>
          ) : recommendationList.map((item) => (
            <div key={item.id} className={`${panelClass} border-r-4 ${severityClasses[item.severity] || ''}`}>
              <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                <div className="min-w-0 flex-1">
                  <div className="mb-2 flex flex-wrap items-center gap-2">
                    <span className="rounded bg-white/70 px-2 py-1 text-xs font-semibold">{item.category}</span>
                    <span className="rounded bg-white/70 px-2 py-1 text-xs">עדיפות {item.priority_score}</span>
                    <span className="rounded bg-white/70 px-2 py-1 text-xs">ביטחון {item.confidence}</span>
                  </div>
                  <h2 className="text-lg font-semibold">{item.title}</h2>
                  {item.rationale && <p className="mt-2 text-sm leading-6">{item.rationale}</p>}
                  {item.recommended_action && (
                    <p className="mt-3 text-sm font-medium">פעולה מומלצת: {item.recommended_action}</p>
                  )}
                  <div className="mt-3 grid gap-3 md:grid-cols-2">
                    <div>
                      <p className="text-xs font-semibold">צעדים הבאים</p>
                      <ul className="mt-1 space-y-1 text-sm">
                        {item.next_steps.map((step) => <li key={step}>• {step}</li>)}
                      </ul>
                    </div>
                    <div>
                      <p className="text-xs font-semibold">מקורות נתונים</p>
                      <p className="mt-1 text-sm">{item.source_systems.join(', ')}</p>
                    </div>
                  </div>
                </div>
                <div className="flex shrink-0 flex-row gap-2 lg:flex-col">
                  <button
                    type="button"
                    onClick={() => updateInsight.mutate({ id: item.insight_id, status: 'acknowledged' })}
                    className="rounded-lg bg-white px-3 py-2 text-sm font-medium text-gray-800 shadow-sm hover:bg-gray-50"
                  >
                    סמן בטיפול
                  </button>
                  <button
                    type="button"
                    onClick={() => updateInsight.mutate({ id: item.insight_id, status: 'resolved' })}
                    className="rounded-lg bg-gray-900 px-3 py-2 text-sm font-medium text-white hover:bg-gray-800"
                  >
                    סמן כטופל
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {activeTab === 'alerts' && (
        <div className={panelClass}>
          <div className="space-y-3">
            {alertList.length === 0 ? (
              <div className={`py-10 text-center ${mutedText}`}>
                <CheckCircle size={42} className="mx-auto mb-3 opacity-60" />
                <p>אין התראות פעילות.</p>
              </div>
            ) : alertList.map((alert) => (
              <div key={alert.id} className={`rounded-lg border-r-4 p-4 ${severityClasses[alert.severity] || ''}`}>
                <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                  <div>
                    <div className="flex items-center gap-2">
                      <AlertTriangle size={16} />
                      <span className="text-sm font-semibold">{alert.title}</span>
                      <span className="rounded bg-white/70 px-2 py-0.5 text-xs">{alert.status}</span>
                    </div>
                    <p className="mt-2 text-sm">{alert.message}</p>
                    <p className="mt-1 text-xs opacity-70">{new Date(alert.created_at).toLocaleString('he-IL')}</p>
                  </div>
                  {alert.status === 'active' && (
                    <div className="flex gap-2">
                      <button type="button" onClick={() => acknowledgeAlert.mutate(alert.id)} className="rounded-lg bg-white px-3 py-2 text-xs text-gray-800">
                        אישור
                      </button>
                      <button type="button" onClick={() => dismissAlert.mutate(alert.id)} className="rounded-lg bg-gray-900 px-3 py-2 text-xs text-white">
                        הסתר
                      </button>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {activeTab === 'tasks' && (
        <div className={panelClass}>
          <div className="mb-4">
            {showNewTask ? (
              <div className="flex gap-2">
                <input
                  type="text"
                  value={newTaskTitle}
                  onChange={(e) => setNewTaskTitle(e.target.value)}
                  placeholder="כותרת משימה"
                  className={`min-w-0 flex-1 rounded-lg border px-3 py-2 text-sm ${
                    darkMode ? 'bg-gray-700 border-gray-600 text-white' : 'border-gray-300'
                  }`}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && newTaskTitle.trim()) createTask.mutate(newTaskTitle);
                  }}
                />
                <button type="button" onClick={() => { if (newTaskTitle.trim()) createTask.mutate(newTaskTitle); }} className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white">
                  הוסף
                </button>
                <button type="button" onClick={() => setShowNewTask(false)} className="rounded-lg p-2 text-gray-400 hover:text-gray-600">
                  <X size={18} />
                </button>
              </div>
            ) : (
              <button type="button" onClick={() => setShowNewTask(true)} className="inline-flex items-center gap-2 text-sm font-medium text-blue-600 hover:text-blue-700">
                <Plus size={18} />
                משימה חדשה
              </button>
            )}
          </div>

          <div className="space-y-2">
            {taskList.length === 0 ? (
              <div className={`py-10 text-center ${mutedText}`}>
                <Clock size={42} className="mx-auto mb-3 opacity-60" />
                <p>אין משימות פתוחות.</p>
              </div>
            ) : taskList.map((task) => (
              <div key={task.id} className={`flex items-center justify-between rounded-lg p-3 ${darkMode ? 'hover:bg-gray-700' : 'hover:bg-gray-50'}`}>
                <div className="flex min-w-0 items-center gap-3">
                  <button
                    type="button"
                    onClick={() => {
                      const nextStatus = task.status === 'open' ? 'in_progress' : task.status === 'in_progress' ? 'done' : 'open';
                      updateTask.mutate({ id: task.id, status: nextStatus });
                    }}
                    className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full border-2 ${
                      task.status === 'done'
                        ? 'bg-green-500 border-green-500'
                        : task.status === 'in_progress'
                          ? 'border-blue-500'
                          : darkMode ? 'border-gray-500' : 'border-gray-300'
                    }`}
                  >
                    {task.status === 'done' && <CheckCircle size={12} className="text-white" />}
                  </button>
                  <div className="min-w-0">
                    <p className={`truncate text-sm font-medium ${task.status === 'done' ? 'line-through text-gray-400' : ''}`}>
                      {task.title}
                    </p>
                    {task.entity_type && (
                      <p className={`text-xs ${mutedText}`}>מקושר אל {task.entity_type} #{task.entity_id}</p>
                    )}
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  {task.due_date && <span className={`text-xs ${mutedText}`}>עד {task.due_date}</span>}
                  <span className={`text-xs font-medium ${statusColor(task.status)}`}>{task.status.replace('_', ' ')}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

export default CFOAlertsTasks;
