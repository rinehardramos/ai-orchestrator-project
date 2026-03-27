import { Agent } from '@/lib/api'

interface AgentCardProps {
  agent: Agent
}

export function AgentCard({ agent }: AgentCardProps) {
  const specializationColors: Record<string, string> = {
    coding: 'bg-blue-500/20 text-blue-400',
    research: 'bg-green-500/20 text-green-400',
    writing: 'bg-purple-500/20 text-purple-400',
    general: 'bg-gray-500/20 text-gray-400',
    expert: 'bg-red-500/20 text-red-400',
  }

  return (
    <div className="agent-card bg-gray-900 rounded-xl p-6 border border-gray-800">
      <div className="flex items-center gap-4 mb-4">
        <div className="w-12 h-12 bg-indigo-600 rounded-full flex items-center justify-center text-xl font-bold">
          {agent.nickname.charAt(0)}
        </div>
        <div>
          <h3 className="text-lg font-semibold text-white">{agent.nickname}</h3>
          <span className={`text-xs px-2 py-1 rounded-full ${specializationColors[agent.specialization] || specializationColors.general}`}>
            {agent.specialization}
          </span>
        </div>
      </div>
      
      <p className="text-gray-400 text-sm mb-4 line-clamp-2">
        {agent.personality}
      </p>
      
      <div className="flex justify-between text-sm text-gray-500 mb-4">
        <span>⭐ {agent.reputation_score.toFixed(2)}</span>
        <span>✓ {agent.tasks_completed} tasks</span>
        <span>{(agent.success_rate * 100).toFixed(0)}% success</span>
      </div>
      
      <div className="flex justify-between items-center pt-4 border-t border-gray-800">
        <span className="text-gray-500 text-sm">{agent.model_id}</span>
        <span className="text-indigo-400 font-medium">${agent.cost_per_task.toFixed(2)}/task</span>
      </div>
    </div>
  )
}
