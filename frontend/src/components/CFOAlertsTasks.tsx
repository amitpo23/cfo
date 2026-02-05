import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, CheckCircle, Clock, Plus, X } from 'lucide-react';
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

interface Props {
  darkMode: boolean;
}

const CFOAlertsTasks: React.FC<Props> = ({ darkMode }) => {
  const [activeTab, setActiveTab] = useState<'alerts' | 'tasks'>('alerts');
  const [showNewTask, setShowNewTask] = useState(false);
  const [newTaskTitle, setNewTaskTitle] = useState('');
  const queryClient = useQueryClient();

  const { data: alerts } = useQuery<Alert[]>({
    queryKey: ['alerts'],
    queryFn: () => apiService.get('/alerts'),
  });

  const { data: tasks } = useQuery<Task[]>({
    queryKey: ['tasks'],
    queryFn: () => apiService.get('/tasks'),
  });

  const dismissAlert = useMutation({
    mutationFn: (id: number) =>
      apiService.patch(`/alerts/${id}`, { status: 'dismissed' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['alerts'] }),
  });

  const acknowledgeAlert = useMutation({
    mutationFn: (id: number) =>
      apiService.patch(`/alerts/${id}`, { status: 'acknowledged' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['alerts'] }),
  });

  const updateTask = useMutation({
    mutationFn: ({ id, status }: { id: number; status: string }) =>
      apiService.patch(`/tasks/${id}`, { status }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['tasks'] }),
  });

  const createTask = useMutation({
    mutationFn: (title: string) =>
      apiService.post('/tasks', { title }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] });
      setNewTaskTitle('');
      setShowNewTask(false);
    },
  });

  const cardClass = `p-6 rounded-2xl ${
    darkMode ? 'bg-gray-800 border border-gray-700' : 'bg-white border border-gray-200'
  }`;

  const alertList = alerts || [];
  const taskList = tasks || [];

  const severityColor = (severity: string) => {
    switch (severity) {
      case 'critical': return 'border-red-500 bg-red-50';
      case 'warning': return 'border-yellow-500 bg-yellow-50';
      default: return 'border-blue-500 bg-blue-50';
    }
  };

  const statusColor = (status: string) => {
    switch (status) {
      case 'done': return 'text-green-500';
      case 'in_progress': return 'text-blue-500';
      default: return 'text-gray-500';
    }
  };

  return (
    <div className={`p-6 space-y-6 ${darkMode ? 'text-white' : 'text-gray-900'}`}>
      <h1 className="text-3xl font-bold">Alerts & Tasks</h1>

      {/* Tab Switcher */}
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => setActiveTab('alerts')}
          className={`px-4 py-2 rounded-xl font-medium transition ${
            activeTab === 'alerts'
              ? 'bg-blue-600 text-white'
              : darkMode ? 'bg-gray-700 text-gray-300' : 'bg-gray-100 text-gray-600'
          }`}
        >
          Alerts ({alertList.filter((a) => a.status === 'active').length})
        </button>
        <button
          type="button"
          onClick={() => setActiveTab('tasks')}
          className={`px-4 py-2 rounded-xl font-medium transition ${
            activeTab === 'tasks'
              ? 'bg-blue-600 text-white'
              : darkMode ? 'bg-gray-700 text-gray-300' : 'bg-gray-100 text-gray-600'
          }`}
        >
          Tasks ({taskList.filter((t) => t.status !== 'done').length})
        </button>
      </div>

      {activeTab === 'alerts' ? (
        <div className={cardClass}>
          <div className="space-y-3">
            {alertList.length === 0 ? (
              <div className={`text-center py-12 ${darkMode ? 'text-gray-500' : 'text-gray-400'}`}>
                <CheckCircle size={48} className="mx-auto mb-3 opacity-50" />
                <p>No alerts - everything looks good</p>
              </div>
            ) : (
              alertList.map((alert) => (
                <div
                  key={alert.id}
                  className={`p-4 rounded-xl border-l-4 ${
                    darkMode ? 'bg-gray-700/50' : ''
                  } ${severityColor(alert.severity)}`}
                >
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-1">
                        <AlertTriangle size={16} className={
                          alert.severity === 'critical' ? 'text-red-500' : 'text-yellow-500'
                        } />
                        <span className={`text-sm font-semibold ${darkMode ? 'text-white' : 'text-gray-900'}`}>
                          {alert.title}
                        </span>
                        <span className={`text-xs px-2 py-0.5 rounded-full ${
                          alert.status === 'active'
                            ? 'bg-red-100 text-red-700'
                            : 'bg-gray-100 text-gray-600'
                        }`}>
                          {alert.status}
                        </span>
                      </div>
                      <p className={`text-sm ${darkMode ? 'text-gray-400' : 'text-gray-600'}`}>
                        {alert.message}
                      </p>
                      <p className={`text-xs mt-1 ${darkMode ? 'text-gray-500' : 'text-gray-400'}`}>
                        {new Date(alert.created_at).toLocaleString()}
                      </p>
                    </div>
                    {alert.status === 'active' && (
                      <div className="flex gap-2 ml-4">
                        <button
                          type="button"
                          onClick={() => acknowledgeAlert.mutate(alert.id)}
                          className="text-xs px-2 py-1 bg-blue-100 text-blue-700 rounded-lg hover:bg-blue-200"
                        >
                          Acknowledge
                        </button>
                        <button
                          type="button"
                          onClick={() => dismissAlert.mutate(alert.id)}
                          className="text-xs px-2 py-1 bg-gray-100 text-gray-600 rounded-lg hover:bg-gray-200"
                        >
                          Dismiss
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      ) : (
        <div className={cardClass}>
          {/* New Task */}
          <div className="mb-4">
            {showNewTask ? (
              <div className="flex gap-2">
                <input
                  type="text"
                  value={newTaskTitle}
                  onChange={(e) => setNewTaskTitle(e.target.value)}
                  placeholder="Task title..."
                  className={`flex-1 px-3 py-2 rounded-xl border text-sm ${
                    darkMode ? 'bg-gray-700 border-gray-600 text-white' : 'border-gray-300'
                  }`}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && newTaskTitle.trim()) createTask.mutate(newTaskTitle);
                  }}
                />
                <button
                  type="button"
                  onClick={() => { if (newTaskTitle.trim()) createTask.mutate(newTaskTitle); }}
                  className="px-4 py-2 bg-blue-600 text-white rounded-xl text-sm"
                >
                  Add
                </button>
                <button
                  type="button"
                  onClick={() => setShowNewTask(false)}
                  className="p-2 text-gray-400 hover:text-gray-600"
                >
                  <X size={18} />
                </button>
              </div>
            ) : (
              <button
                type="button"
                onClick={() => setShowNewTask(true)}
                className="flex items-center gap-2 text-blue-500 hover:text-blue-600 text-sm font-medium"
              >
                <Plus size={18} />
                New Task
              </button>
            )}
          </div>

          {/* Task List */}
          <div className="space-y-2">
            {taskList.length === 0 ? (
              <div className={`text-center py-12 ${darkMode ? 'text-gray-500' : 'text-gray-400'}`}>
                <Clock size={48} className="mx-auto mb-3 opacity-50" />
                <p>No tasks yet</p>
              </div>
            ) : (
              taskList.map((task) => (
                <div
                  key={task.id}
                  className={`p-3 rounded-xl flex items-center justify-between ${
                    darkMode ? 'hover:bg-gray-700' : 'hover:bg-gray-50'
                  } transition`}
                >
                  <div className="flex items-center gap-3">
                    <button
                      type="button"
                      onClick={() => {
                        const nextStatus = task.status === 'open'
                          ? 'in_progress'
                          : task.status === 'in_progress'
                            ? 'done'
                            : 'open';
                        updateTask.mutate({ id: task.id, status: nextStatus });
                      }}
                      className={`w-5 h-5 rounded-full border-2 flex items-center justify-center ${
                        task.status === 'done'
                          ? 'bg-green-500 border-green-500'
                          : task.status === 'in_progress'
                            ? 'border-blue-500'
                            : darkMode ? 'border-gray-500' : 'border-gray-300'
                      }`}
                    >
                      {task.status === 'done' && (
                        <CheckCircle size={12} className="text-white" />
                      )}
                    </button>
                    <div>
                      <p className={`text-sm font-medium ${
                        task.status === 'done' ? 'line-through text-gray-400' : ''
                      }`}>
                        {task.title}
                      </p>
                      {task.entity_type && (
                        <p className={`text-xs ${darkMode ? 'text-gray-500' : 'text-gray-400'}`}>
                          Linked to: {task.entity_type} #{task.entity_id}
                        </p>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    {task.due_date && (
                      <span className={`text-xs ${darkMode ? 'text-gray-400' : 'text-gray-500'}`}>
                        Due: {task.due_date}
                      </span>
                    )}
                    <span className={`text-xs font-medium capitalize ${statusColor(task.status)}`}>
                      {task.status.replace('_', ' ')}
                    </span>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default CFOAlertsTasks;
