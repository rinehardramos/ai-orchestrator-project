'use client'

import { useState, useEffect } from 'react'
import { getBounties, Bounty, rateBounty } from '@/lib/api'

interface BountyListProps {
  refreshTrigger?: number
}

export function BountyList({ refreshTrigger }: BountyListProps) {
  const [bounties, setBounties] = useState<Bounty[]>([])
  const [loading, setLoading] = useState(true)
  const [ratingBounty, setRatingBounty] = useState<string | null>(null)
  const [rating, setRating] = useState(5)
  const [feedback, setFeedback] = useState('')

  useEffect(() => {
    loadBounties()
  }, [refreshTrigger])

  const loadBounties = async () => {
    try {
      const data = await getBounties()
      setBounties(data)
    } catch (err) {
      console.error('Failed to load bounties:', err)
    } finally {
      setLoading(false)
    }
  }

  const handleRate = async (bountyId: string) => {
    try {
      await rateBounty(bountyId, rating, feedback)
      setRatingBounty(null)
      setRating(5)
      setFeedback('')
      loadBounties()
    } catch (err) {
      console.error('Failed to rate:', err)
    }
  }

  const statusColors: Record<string, string> = {
    open: 'bg-yellow-500/20 text-yellow-400',
    claimed: 'bg-blue-500/20 text-blue-400',
    in_progress: 'bg-blue-500/20 text-blue-400',
    completed: 'bg-green-500/20 text-green-400',
    cancelled: 'bg-gray-500/20 text-gray-400',
    failed: 'bg-red-500/20 text-red-400',
  }

  if (loading) {
    return <div className="text-gray-400">Loading bounties...</div>
  }

  if (bounties.length === 0) {
    return <div className="text-gray-400">No bounties yet. Create one above!</div>
  }

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold text-white">Your Bounties</h2>
      
      {bounties.map((bounty) => (
        <div key={bounty.id} className="bg-gray-900 rounded-xl p-6 border border-gray-800">
          <div className="flex justify-between items-start mb-4">
            <div>
              <h3 className="text-lg font-semibold text-white">{bounty.title}</h3>
              <p className="text-gray-400 text-sm mt-1">{bounty.description.slice(0, 150)}...</p>
            </div>
            <span className={`px-3 py-1 rounded-full text-sm ${statusColors[bounty.status]}`}>
              {bounty.status}
            </span>
          </div>

          <div className="flex gap-6 text-sm text-gray-500 mb-4">
            <span>💰 ${bounty.price}</span>
            <span>⏱ {bounty.duration_minutes} min</span>
            <span>🎯 {bounty.difficulty}</span>
            {bounty.claimed_by && <span>🤖 {bounty.claimed_by}</span>}
          </div>

          {bounty.status === 'completed' && !bounty.user_rating && (
            <div className="border-t border-gray-800 pt-4">
              {ratingBounty === bounty.id ? (
                <div className="space-y-3">
                  <div className="flex gap-2">
                    {[1, 2, 3, 4, 5].map((n) => (
                      <button
                        key={n}
                        onClick={() => setRating(n)}
                        className={`text-2xl ${n <= rating ? 'text-yellow-400' : 'text-gray-600'}`}
                      >
                        ★
                      </button>
                    ))}
                  </div>
                  <input
                    type="text"
                    value={feedback}
                    onChange={(e) => setFeedback(e.target.value)}
                    placeholder="Optional feedback..."
                    className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white text-sm"
                  />
                  <div className="flex gap-2">
                    <button
                      onClick={() => handleRate(bounty.id)}
                      className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm"
                    >
                      Submit Rating
                    </button>
                    <button
                      onClick={() => setRatingBounty(null)}
                      className="px-4 py-2 bg-gray-700 text-white rounded-lg text-sm"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <button
                  onClick={() => setRatingBounty(bounty.id)}
                  className="text-indigo-400 hover:text-indigo-300 text-sm"
                >
                  Rate this bounty ⭐
                </button>
              )}
            </div>
          )}

          {bounty.user_rating && (
            <div className="border-t border-gray-800 pt-4 text-sm text-gray-500">
              Your rating: {'★'.repeat(bounty.user_rating)}{'☆'.repeat(5 - bounty.user_rating)}
            </div>
          )}

          {bounty.result && (
            <div className="border-t border-gray-800 pt-4 mt-4">
              <h4 className="text-sm font-medium text-gray-300 mb-2">Result:</h4>
              <p className="text-gray-400 text-sm">{bounty.result.slice(0, 300)}...</p>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
