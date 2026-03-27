'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { getMe, User } from '@/lib/api'

export function useAuth() {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)
  const router = useRouter()

  useEffect(() => {
    const token = localStorage.getItem('token')
    if (!token) {
      setLoading(false)
      return
    }

    getMe()
      .then(setUser)
      .catch(() => {
        localStorage.removeItem('token')
        router.push('/auth/login')
      })
      .finally(() => setLoading(false))
  }, [router])

  const logout = () => {
    localStorage.removeItem('token')
    router.push('/')
  }

  return { user, loading, logout }
}
