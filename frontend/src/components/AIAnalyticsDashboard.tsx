import React, { useState } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  Legend,
  ScatterChart,
  Scatter,
} from 'recharts';
import api from '../services/api';

interface Anomaly {
  anomaly_id: string;
  anomaly_type: string;
  description: string;
  actual_value: number;
  expected_value: number | null;
  deviation_percentage: number;
  risk_level: string;
  confidence_score: number;
  recommendation: string;
}

interface FinancialRisk {
  risk_id: string;
  risk_type: string;
  title: string;
  description: string;
  risk_level: string;
  probability: number;
  potential_impact: number;
  expected_loss: number;
  mitigation_actions: string[];
  trend: string;
}

interface AIInsight {
  insight_id: string;
  insight_type: string;
  title: string;
  description: string;
  impact_amount: number;
  confidence: number;
  priority: string;
  suggested_actions: string[];
}

interface AIRecommendation {
  recommendation_id: string;
  category: string;
  title: string;
  description: string;
  expected_benefit: number;
  implementation_cost: number;
  roi: number;
  effort_level: string;
  time_to_implement: string;
  priority_score: number;
}

const COLORS = ['#3B82F6', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6'];

export const AIAnalyticsDashboard: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'anomalies' | 'risks' | 'insights' | 'recommendations' | 'chat'>('insights');
  const [chatQuestion, setChatQuestion] = useState('');
  const [chatHistory, setChatHistory] = useState<Array<{role: string, content: string}>>([]);

  // Fetch anomalies
  const { data: anomalies, isLoading: loadingAnomalies } = useQuery({
    queryKey: ['ai-anomalies'],
    queryFn: async () => {
      const response = await api.get('/api/financial/ai/anomalies');
      return response.data.data as Anomaly[];
    },
  });

  // Fetch risks
  const { data: risks, isLoading: loadingRisks } = useQuery({
    queryKey: ['ai-risks'],
    queryFn: async () => {
      const response = await api.get('/api/financial/ai/risks');
      return response.data.data as FinancialRisk[];
    },
  });

  // Fetch insights
  const { data: insights, isLoading: loadingInsights } = useQuery({
    queryKey: ['ai-insights'],
    queryFn: async () => {
      const response = await api.get('/api/financial/ai/insights');
      return response.data.data as AIInsight[];
    },
  });

  // Fetch recommendations
  const { data: recommendations, isLoading: loadingRecommendations } = useQuery({
    queryKey: ['ai-recommendations'],
    queryFn: async () => {
      const response = await api.get('/api/financial/ai/recommendations');
      return response.data.data as AIRecommendation[];
    },
  });

  // AI Analysis mutation
  const analysisMutation = useMutation({
    mutationFn: async (question: string) => {
      const response = await api.post('/api/financial/ai/analyze', { question });
      return response.data.data.analysis;
    },
    onSuccess: (analysis) => {
      setChatHistory([
        ...chatHistory,
        { role: 'user', content: chatQuestion },
        { role: 'assistant', content: analysis }
      ]);
      setChatQuestion('');
    },
  });

  const handleAskQuestion = () => {
    if (chatQuestion.trim()) {
      analysisMutation.mutate(chatQuestion);
    }
  };

  const formatCurrency = (value: number) => `₪${value.toLocaleString()}`;

  const getRiskLevelColor = (level: string) => {
    switch (level) {
      case 'critical': return 'bg-red-100 text-red-800 border-red-300';
      case 'high': return 'bg-orange-100 text-orange-800 border-orange-300';
      case 'medium': return 'bg-yellow-100 text-yellow-800 border-yellow-300';
      case 'low': return 'bg-green-100 text-green-800 border-green-300';
      default: return 'bg-gray-100 text-gray-800 border-gray-300';
    }
  };

  const getRiskLevelLabel = (level: string) => {
    switch (level) {
      case 'critical': return 'קריטי';
      case 'high': return 'גבוה';
      case 'medium': return 'בינוני';
      case 'low': return 'נמוך';
      default: return level;
    }
  };

  const getInsightTypeIcon = (type: string) => {
    switch (type) {
      case 'cost_saving': return '💰';
      case 'revenue_opportunity': return '📈';
      case 'risk_alert': return '⚠️';
      case 'efficiency_tip': return '⚡';
      case 'trend_insight': return '📊';
      default: return '💡';
    }
  };

  const getInsightTypeLabel = (type: string) => {
    switch (type) {
      case 'cost_saving': return 'חיסכון בעלויות';
      case 'revenue_opportunity': return 'הזדמנות הכנסה';
      case 'risk_alert': return 'התראת סיכון';
      case 'efficiency_tip': return 'יעילות';
      case 'trend_insight': return 'מגמה';
      default: return type;
    }
  };

  const getPriorityColor = (priority: string) => {
    switch (priority) {
      case 'high': return 'text-red-600';
      case 'medium': return 'text-yellow-600';
      case 'low': return 'text-green-600';
      default: return 'text-gray-600';
    }
  };

  // Risk summary
  const riskSummary = risks?.reduce((acc, risk) => {
    acc[risk.risk_level] = (acc[risk.risk_level] || 0) + 1;
    return acc;
  }, {} as Record<string, number>) || {};

  const totalExpectedLoss = risks?.reduce((sum, risk) => sum + risk.expected_loss, 0) || 0;

  // Calculate insight impact
  const totalImpact = insights?.reduce((sum, insight) => sum + insight.impact_amount, 0) || 0;

  // Calculate recommendation ROI
  const totalBenefit = recommendations?.reduce((sum, rec) => sum + rec.expected_benefit, 0) || 0;

  if (loadingInsights) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500"></div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6 bg-gray-50 min-h-screen" dir="rtl">
      {/* Header */}
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">ניתוח AI מתקדם</h1>
          <p className="text-gray-600 mt-1">תובנות, סיכונים והמלצות מבוססי בינה מלאכותית</p>
        </div>
        <div className="flex items-center gap-2 bg-purple-100 text-purple-800 px-4 py-2 rounded-lg">
          <span className="text-xl">🤖</span>
          <span className="font-medium">מופעל על ידי AI</span>
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
        <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-100">
          <h3 className="text-sm font-medium text-gray-500">אנומליות שזוהו</h3>
          <p className="text-3xl font-bold text-purple-600 mt-2">{anomalies?.length || 0}</p>
          <p className="text-xs text-gray-400 mt-1">ב-90 יום אחרונים</p>
        </div>
        <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-100">
          <h3 className="text-sm font-medium text-gray-500">סיכונים פעילים</h3>
          <p className="text-3xl font-bold text-red-600 mt-2">{risks?.length || 0}</p>
          <p className="text-xs text-gray-400 mt-1">
            הפסד צפוי: {formatCurrency(totalExpectedLoss)}
          </p>
        </div>
        <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-100">
          <h3 className="text-sm font-medium text-gray-500">תובנות חדשות</h3>
          <p className="text-3xl font-bold text-blue-600 mt-2">{insights?.length || 0}</p>
          <p className="text-xs text-gray-400 mt-1">
            פוטנציאל: {formatCurrency(totalImpact)}
          </p>
        </div>
        <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-100">
          <h3 className="text-sm font-medium text-gray-500">המלצות לביצוע</h3>
          <p className="text-3xl font-bold text-green-600 mt-2">{recommendations?.length || 0}</p>
          <p className="text-xs text-gray-400 mt-1">
            תועלת: {formatCurrency(totalBenefit)}
          </p>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-2 border-b border-gray-200">
        {[
          { id: 'insights', label: '💡 תובנות' },
          { id: 'anomalies', label: '🔍 אנומליות' },
          { id: 'risks', label: '⚠️ סיכונים' },
          { id: 'recommendations', label: '📋 המלצות' },
          { id: 'chat', label: '💬 שאל את ה-AI' },
        ].map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id as any)}
            className={`px-6 py-3 font-medium transition-colors ${
              activeTab === tab.id
                ? 'text-blue-600 border-b-2 border-blue-600'
                : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      {activeTab === 'insights' && (
        <div className="space-y-4">
          {insights?.map((insight) => (
            <div
              key={insight.insight_id}
              className="bg-white rounded-xl shadow-sm p-6 border border-gray-100 hover:border-blue-200 transition-colors"
            >
              <div className="flex justify-between items-start">
                <div className="flex gap-4">
                  <span className="text-3xl">{getInsightTypeIcon(insight.insight_type)}</span>
                  <div>
                    <div className="flex items-center gap-2">
                      <h3 className="text-lg font-bold text-gray-900">{insight.title}</h3>
                      <span className={`text-sm font-medium ${getPriorityColor(insight.priority)}`}>
                        ({insight.priority === 'high' ? 'עדיפות גבוהה' : 
                          insight.priority === 'medium' ? 'עדיפות בינונית' : 'עדיפות נמוכה'})
                      </span>
                    </div>
                    <p className="text-gray-600 mt-1">{insight.description}</p>
                    <span className="inline-block mt-2 px-3 py-1 bg-blue-100 text-blue-800 rounded-full text-sm">
                      {getInsightTypeLabel(insight.insight_type)}
                    </span>
                  </div>
                </div>
                <div className="text-left">
                  <p className="text-sm text-gray-500">השפעה פוטנציאלית</p>
                  <p className="text-2xl font-bold text-green-600">{formatCurrency(insight.impact_amount)}</p>
                  <p className="text-xs text-gray-400">ביטחון: {(insight.confidence * 100).toFixed(0)}%</p>
                </div>
              </div>
              
              {insight.suggested_actions?.length > 0 && (
                <div className="mt-4 pt-4 border-t border-gray-100">
                  <h4 className="text-sm font-medium text-gray-700 mb-2">פעולות מומלצות:</h4>
                  <ul className="space-y-1">
                    {insight.suggested_actions.map((action, i) => (
                      <li key={i} className="flex items-center gap-2 text-sm text-gray-600">
                        <span className="w-1.5 h-1.5 bg-blue-500 rounded-full"></span>
                        {action}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {activeTab === 'anomalies' && (
        <div className="space-y-4">
          {anomalies?.map((anomaly) => (
            <div
              key={anomaly.anomaly_id}
              className={`bg-white rounded-xl shadow-sm p-6 border ${getRiskLevelColor(anomaly.risk_level)}`}
            >
              <div className="flex justify-between items-start">
                <div>
                  <h3 className="text-lg font-bold text-gray-900">{anomaly.description}</h3>
                  <p className="text-sm text-gray-500 mt-1">סוג: {anomaly.anomaly_type}</p>
                  <p className="text-sm text-gray-600 mt-2">{anomaly.recommendation}</p>
                </div>
                <div className="text-left">
                  <span className={`px-3 py-1 rounded-full text-sm font-medium ${getRiskLevelColor(anomaly.risk_level)}`}>
                    {getRiskLevelLabel(anomaly.risk_level)}
                  </span>
                  <p className="mt-2 text-2xl font-bold">{formatCurrency(anomaly.actual_value)}</p>
                  {anomaly.expected_value && (
                    <p className="text-sm text-gray-500">צפוי: {formatCurrency(anomaly.expected_value)}</p>
                  )}
                  <p className="text-sm text-red-600">
                    סטייה: {anomaly.deviation_percentage.toFixed(1)}%
                  </p>
                </div>
              </div>
            </div>
          ))}
          
          {(!anomalies || anomalies.length === 0) && (
            <div className="text-center py-12 bg-white rounded-xl">
              <span className="text-5xl">✅</span>
              <h3 className="text-xl font-bold text-gray-900 mt-4">לא זוהו אנומליות</h3>
              <p className="text-gray-500">המערכת לא מצאה פעילות חריגה</p>
            </div>
          )}
        </div>
      )}

      {activeTab === 'risks' && (
        <div className="space-y-6">
          {/* Risk Summary Chart */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-100">
              <h3 className="text-lg font-bold text-gray-900 mb-4">התפלגות סיכונים</h3>
              <ResponsiveContainer width="100%" height={200}>
                <PieChart>
                  <Pie
                    data={Object.entries(riskSummary).map(([level, count]) => ({
                      name: getRiskLevelLabel(level),
                      value: count,
                    }))}
                    dataKey="value"
                    nameKey="name"
                    cx="50%"
                    cy="50%"
                    outerRadius={80}
                    label
                  >
                    {Object.keys(riskSummary).map((_, index) => (
                      <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip />
                  <Legend />
                </PieChart>
              </ResponsiveContainer>
            </div>
            
            <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-100">
              <h3 className="text-lg font-bold text-gray-900 mb-4">השפעה צפויה</h3>
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={risks?.map(r => ({
                  name: r.title.substring(0, 15),
                  impact: r.potential_impact,
                  expected: r.expected_loss,
                }))}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="name" />
                  <YAxis tickFormatter={(v) => `₪${(v / 1000).toFixed(0)}K`} />
                  <Tooltip formatter={(v: number) => formatCurrency(v)} />
                  <Bar dataKey="expected" fill="#EF4444" name="הפסד צפוי" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Risk Cards */}
          {risks?.map((risk) => (
            <div
              key={risk.risk_id}
              className={`bg-white rounded-xl shadow-sm p-6 border ${getRiskLevelColor(risk.risk_level)}`}
            >
              <div className="flex justify-between items-start">
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <h3 className="text-lg font-bold text-gray-900">{risk.title}</h3>
                    <span className={`px-3 py-1 rounded-full text-xs font-medium ${getRiskLevelColor(risk.risk_level)}`}>
                      {getRiskLevelLabel(risk.risk_level)}
                    </span>
                  </div>
                  <p className="text-gray-600 mt-2">{risk.description}</p>
                  
                  <div className="grid grid-cols-3 gap-4 mt-4">
                    <div>
                      <p className="text-sm text-gray-500">הסתברות</p>
                      <p className="text-lg font-bold">{(risk.probability * 100).toFixed(0)}%</p>
                    </div>
                    <div>
                      <p className="text-sm text-gray-500">השפעה פוטנציאלית</p>
                      <p className="text-lg font-bold">{formatCurrency(risk.potential_impact)}</p>
                    </div>
                    <div>
                      <p className="text-sm text-gray-500">הפסד צפוי</p>
                      <p className="text-lg font-bold text-red-600">{formatCurrency(risk.expected_loss)}</p>
                    </div>
                  </div>
                </div>
              </div>
              
              {risk.mitigation_actions?.length > 0 && (
                <div className="mt-4 pt-4 border-t border-gray-100">
                  <h4 className="text-sm font-medium text-gray-700 mb-2">פעולות מיטיגציה:</h4>
                  <ul className="space-y-1">
                    {risk.mitigation_actions.map((action, i) => (
                      <li key={i} className="flex items-center gap-2 text-sm text-gray-600">
                        <span className="w-1.5 h-1.5 bg-orange-500 rounded-full"></span>
                        {action}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {activeTab === 'recommendations' && (
        <div className="space-y-4">
          {recommendations?.sort((a, b) => b.priority_score - a.priority_score).map((rec) => (
            <div
              key={rec.recommendation_id}
              className="bg-white rounded-xl shadow-sm p-6 border border-gray-100 hover:border-green-200 transition-colors"
            >
              <div className="flex justify-between items-start">
                <div className="flex-1">
                  <div className="flex items-center gap-3">
                    <span className="px-2 py-1 bg-blue-100 text-blue-800 rounded text-sm">
                      {rec.category}
                    </span>
                    <h3 className="text-lg font-bold text-gray-900">{rec.title}</h3>
                  </div>
                  <p className="text-gray-600 mt-2">{rec.description}</p>
                  
                  <div className="grid grid-cols-4 gap-4 mt-4">
                    <div>
                      <p className="text-sm text-gray-500">תועלת צפויה</p>
                      <p className="text-lg font-bold text-green-600">{formatCurrency(rec.expected_benefit)}</p>
                    </div>
                    <div>
                      <p className="text-sm text-gray-500">עלות יישום</p>
                      <p className="text-lg font-bold">{formatCurrency(rec.implementation_cost)}</p>
                    </div>
                    <div>
                      <p className="text-sm text-gray-500">ROI</p>
                      <p className="text-lg font-bold text-blue-600">
                        {rec.roi === Infinity ? '∞' : `${rec.roi.toFixed(0)}%`}
                      </p>
                    </div>
                    <div>
                      <p className="text-sm text-gray-500">זמן יישום</p>
                      <p className="text-lg font-bold">{rec.time_to_implement}</p>
                    </div>
                  </div>
                </div>
                <div className="text-center">
                  <div className="w-16 h-16 rounded-full bg-gradient-to-r from-green-400 to-blue-500 flex items-center justify-center">
                    <span className="text-white text-xl font-bold">{rec.priority_score}</span>
                  </div>
                  <p className="text-xs text-gray-500 mt-1">ציון עדיפות</p>
                </div>
              </div>
              
              <div className="mt-4 flex items-center gap-4">
                <span className={`px-3 py-1 rounded-full text-sm font-medium ${
                  rec.effort_level === 'low' ? 'bg-green-100 text-green-800' :
                  rec.effort_level === 'medium' ? 'bg-yellow-100 text-yellow-800' :
                  'bg-red-100 text-red-800'
                }`}>
                  מאמץ: {rec.effort_level === 'low' ? 'נמוך' : rec.effort_level === 'medium' ? 'בינוני' : 'גבוה'}
                </span>
                <button className="bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 text-sm">
                  התחל יישום
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {activeTab === 'chat' && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
          {/* Chat History */}
          <div className="h-96 overflow-y-auto p-6 space-y-4">
            {chatHistory.length === 0 ? (
              <div className="text-center py-12">
                <span className="text-5xl">🤖</span>
                <h3 className="text-xl font-bold text-gray-900 mt-4">שאל את ה-AI</h3>
                <p className="text-gray-500">שאל שאלות על המצב הפיננסי של העסק</p>
                <div className="mt-4 space-y-2">
                  <p className="text-sm text-gray-400">דוגמאות לשאלות:</p>
                  <div className="flex flex-wrap gap-2 justify-center">
                    {[
                      'מה מצב תזרים המזומנים?',
                      'איפה אפשר לחסוך?',
                      'מה הסיכונים העיקריים?',
                      'איך לשפר את הרווחיות?',
                    ].map((q) => (
                      <button
                        key={q}
                        onClick={() => setChatQuestion(q)}
                        className="px-3 py-1 bg-gray-100 rounded-full text-sm text-gray-600 hover:bg-gray-200"
                      >
                        {q}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            ) : (
              chatHistory.map((msg, i) => (
                <div
                  key={i}
                  className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
                >
                  <div
                    className={`max-w-[80%] p-4 rounded-xl ${
                      msg.role === 'user'
                        ? 'bg-blue-600 text-white'
                        : 'bg-gray-100 text-gray-900'
                    }`}
                  >
                    <p className="whitespace-pre-wrap">{msg.content}</p>
                  </div>
                </div>
              ))
            )}
            {analysisMutation.isPending && (
              <div className="flex justify-start">
                <div className="bg-gray-100 p-4 rounded-xl">
                  <div className="flex gap-2">
                    <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"></div>
                    <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0.2s' }}></div>
                    <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0.4s' }}></div>
                  </div>
                </div>
              </div>
            )}
          </div>
          
          {/* Input */}
          <div className="border-t border-gray-200 p-4">
            <div className="flex gap-4">
              <input
                type="text"
                value={chatQuestion}
                onChange={(e) => setChatQuestion(e.target.value)}
                onKeyPress={(e) => e.key === 'Enter' && handleAskQuestion()}
                placeholder="שאל שאלה על המצב הפיננסי..."
                className="flex-1 rounded-lg border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
              />
              <button
                onClick={handleAskQuestion}
                disabled={analysisMutation.isPending || !chatQuestion.trim()}
                className="bg-blue-600 text-white px-6 py-2 rounded-lg hover:bg-blue-700 disabled:opacity-50"
              >
                שלח
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default AIAnalyticsDashboard;
