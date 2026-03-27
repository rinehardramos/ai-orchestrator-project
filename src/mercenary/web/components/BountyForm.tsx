'use client'

import { useState, useEffect } from 'react'
import { createBounty, getBounties, Bounty } from '@/lib/api'

interface BountyFormProps {
  onCreated?: () => void
}

export function BountyForm({ onCreated }: BountyFormProps) {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [price, setPrice] = useState('50')
  const [duration, setDuration] = useState('60')
  const [specialization, setSpecialization] = useState('general')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    setSuccess(false)

    try {
      await createBounty({
        title,
        description,
        price: parseFloat(price),
        duration_minutes: parseInt(duration),
        specialization,
      })
      setSuccess(true)
      setTitle('')
      setDescription('')
      setPrice('50')
      onCreated?.()
    } catch (err: any) {
      setError(err.message || 'Failed to create bounty')
    } finally {
      setLoading(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-6 bg-gray-900 rounded-xl p-6 border border-gray-800">
      <h2 className="text-xl font-semibold text-white">Post a New Bounty</h2>

      {error && (
        <div className="bg-red-500/10 border border-red-500 text-red-400 px-4 py-3 rounded-lg">
          {error}
        </div>
      )}

      {success && (
        <div className="bg-green-500/10 border border-green-500 text-green-400 px-4 py-3 rounded-lg">
          Bounty posted! An agent will claim it shortly.
        </div>
      )}

      <div>
        <label className="block text-sm font-medium text-gray-300 mb-2">
          Mission Title
        </label>
        <input
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          required
          className="w-full px-4 py-3 bg-gray-800 border border-gray-700 rounded-lg text-white focus:ring-2 focus:ring-indigo-500"
          placeholder="Create a PDF report about AI trends"
        />
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-300 mb-2">
          Mission Brief
        </label>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          required
          rows={4}
          className="w-full px-4 py-3 bg-gray-800 border border-gray-700 rounded-lg text-white focus:ring-2 focus:ring-indigo-500"
          placeholder="Describe what you need in detail..."
        />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-300 mb-2">
            Bounty ($)
          </label>
          <input
            type="number"
            value={price}
            onChange={(e) => setPrice(e.target.value)}
            required
            min={5}
            max={1000}
            className="w-full px-4 py-3 bg-gray-800 border border-gray-700 rounded-lg text-white focus:ring-2 focus:ring-indigo-500"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-300 mb-2">
            Deadline
          </label>
          <select
            value={duration}
            onChange={(e) => setDuration(e.target.value)}
            className="w-full px-4 py-3 bg-gray-800 border border-gray-700 rounded-lg text-white focus:ring-2 focus:ring-indigo-500"
          >
            <option value="30">30 minutes</option>
            <option value="60">1 hour</option>
            <option value="120">2 hours</option>
            <option value="240">4 hours</option>
            <option value="480">8 hours</option>
            <option value="1440">24 hours</option>
          </select>
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-300 mb-2">
          Specialization
        </label>
        <select
          value={specialization}
          onChange={(e) => setSpecialization(e.target.value)}
          className="w-full px-4 py-3 bg-gray-800 border border-gray-700 rounded-lg text-white focus:ring-2 focus:ring-indigo-500"
        >
          <option value="general">General</option>
          <option value="coding">Coding</option>
          <option value="research">Research</option>
          <option value="writing">Writing</option>
        </select>
      </div>

      <button
        type="submit"
        disabled={loading}
        className="w-full py-3 bg-indigo-600 text-white rounded-lg font-semibold hover:bg-indigo-700 transition disabled:opacity-50"
      >
        {loading ? 'Posting...' : 'Post Bounty'}
      </button>
    </form>
  )
}
