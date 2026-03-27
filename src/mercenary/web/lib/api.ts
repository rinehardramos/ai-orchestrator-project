import axios from 'axios'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8001'

const api = axios.create({
  baseURL: API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
})

api.interceptors.request.use((config) => {
  if (typeof window !== 'undefined') {
    const token = localStorage.getItem('token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
  }
  return config
})

export interface Agent {
  nickname: string
  model_id: string
  provider: string
  specialization: string
  personality: string
  reputation_score: number
  tasks_completed: number
  success_rate: number
  avg_completion_time: number | null
  cost_per_task: number
  is_available: boolean
  created_at: string
}

export interface Bounty {
  id: string
  user_id: string
  title: string
  description: string
  price: number
  duration_minutes: number
  difficulty: string
  specialization: string
  status: string
  claimed_by: string | null
  claimed_at: string | null
  completed_at: string | null
  result: string | null
  user_rating: number | null
  created_at: string
}

export interface User {
  id: string
  email: string
  display_name: string | null
  balance: number
  created_at: string
}

export interface Transaction {
  id: string
  amount: number
  transaction_type: string
  status: string
  created_at: string
}

// Auth
export async function signup(email: string, password: string, display_name?: string) {
  const { data } = await api.post('/auth/signup', { email, password, display_name })
  return data
}

export async function login(email: string, password: string) {
  const { data } = await api.post('/auth/login', { email, password })
  return data
}

export async function getMe(): Promise<User> {
  const { data } = await api.get('/auth/me')
  return data
}

// Agents
export async function getAgents(): Promise<Agent[]> {
  const { data } = await api.get('/agents')
  return data
}

export async function getAgent(nickname: string): Promise<Agent> {
  const { data } = await api.get(`/agents/${nickname}`)
  return data
}

// Bounties
export async function getBounties(status?: string): Promise<Bounty[]> {
  const { data } = await api.get('/bounties', { params: { status } })
  return data
}

export async function getBounty(id: string): Promise<Bounty> {
  const { data } = await api.get(`/bounties/${id}`)
  return data
}

export async function createBounty(bounty: {
  title: string
  description: string
  price: number
  duration_minutes: number
  specialization?: string
}): Promise<Bounty> {
  const { data } = await api.post('/bounties', bounty)
  return data
}

export async function rateBounty(id: string, rating: number, feedback?: string): Promise<Bounty> {
  const { data } = await api.post(`/bounties/${id}/rate`, { rating, feedback })
  return data
}

export async function cancelBounty(id: string): Promise<void> {
  await api.delete(`/bounties/${id}`)
}

// Wallet
export async function getBalance(): Promise<{ balance: number; pending: number }> {
  const { data } = await api.get('/wallet/balance')
  return data
}

export async function getTransactions(): Promise<Transaction[]> {
  const { data } = await api.get('/wallet/transactions')
  return data
}

export async function createDeposit(amount: number): Promise<{ transaction_id: string }> {
  const { data } = await api.post('/wallet/deposit', { amount })
  return data
}
