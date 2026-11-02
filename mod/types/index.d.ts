export type Pair = [string, number]
// [name, calls, tokens]: exact for subagents, estimated from result size for MCP servers and tools
export type Call = [string, number, number]

// one prompt: tokens in (prompt side, incl. cache) and out, list price when known, model requests, what it called
export type Turn = {
  i: number
  text: string
  in: number
  out: number
  usd: number | null
  requests: number
  agents: Call[]
  runs: Run[]
  mcp: Call[]
  tools: Call[]
}

// one subagent run: what it was asked to do and what it cost; depth 2+ = spawned by another subagent
export type Run = {
  type: string
  desc: string
  depth: number
  tokens: number
  out: number
  usd: number | null
  model: string
}

// budgets.json against today: warn lists the budgets at 80% or more; error is a budgets.json that cannot be read
export type Budget = { error?: string; warn?: { text: string; pct: number; state: 'near' | 'over' }[] }

export type SessionView = {
  id: string
  empty: boolean
  title?: string
  prompts?: number
  tokens?: number
  output?: number
  usd?: number | null
  main?: number
  agents?: number
  runs?: number
  owners?: Pair[]
  skills?: Pair[]
  last?: { i: number; text: string; tokens: number; agents: number } | null
  turns?: Turn[]
  budget?: Budget | null
  context?: number  // tokens in the last main-thread request
  updatedAt?: number
  error?: string
}

// the numbers a refresh animates from, so a new total counts up instead of jumping
export type Totals = { tokens: number; usd: number; main: number; agents: number }

// pane motion: spinner while the CLI runs, tween progress t (0..1) after it, glow on the turn that just landed
export type Motion = {
  busy: boolean
  frame: number
  from: Totals | null
  t: number
  delta: number
  fresh: number | null
  glow: boolean
}

declare module 'claude-code' {
  interface PluginState {
    tokscope: { view: SessionView | null; motion: Motion }
  }
}
