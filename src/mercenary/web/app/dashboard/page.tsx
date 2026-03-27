'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { useAuth } from '@/lib/auth'
import { BountyForm } from '@/components/BountyForm'
import { BountyList } from '@/components/BountyList'
import { useState } from 'react'

export default function DashboardPage() {
  const { user, loading, logout } = useAuth()
  const router = useRouter()
  const [refreshTrigger, setRefreshTrigger] = useState(0)

  useEffect(() => {
    if (!loading && !user) {
      router.push('/auth/login')
    }
  }, [user, loading, router])

  if (loading || !user) {
    return (
      <main className="min-h-screen gradient-bg flex items-center justify-center">
        <div className="text-white">Loading...</div>
      </main>
    )
  }

  return (
    <main className="min-h-screen bg-gray-950">
      {/* Header */}
      <header className="bg-gray-900 border-b border-gray-800">
        <div className="max-w-6xl mx-auto px-4 py-4 flex justify-between items-center">
          <Link href="/" className="text-xl font-bold text-white">
            Agent Mercenaries
          </Link>
          <div className="flex items-center gap-6">
            <div className="text-right">
              <p className="text-white font-medium">{user.display_name || user.email}</p>
              <p className="text-gray-400 text-sm">Balance: ${user.balance.toFixed(2)}</p>
            </div>
            <button
              onClick={logout}
              className="px-4 py-2 bg-gray-800 text-gray-300 rounded-lg hover:bg-gray-700 transition"
            >
              Sign Out
            </button>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <div className="max-w-6xl mx-auto px-4 py-8">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          {/* Left Column - Bounty Form */}
          <div className="lg:col-span-1">
            <BountyForm onCreated={() => setRefreshTrigger((r) => r + 1)} />
          </div>

          {/* Right Column - Bounty List */}
          <div className="lg:col-span-2">
            <BountyList refreshTrigger={refreshTrigger} />
          </div>
        </div>
      </div>
    </main>
  )
}
