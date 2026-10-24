import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register, Timer } from 'claude-code'

import type { Call, Motion, Run, SessionView, Totals, Turn } from '../types'

// all parsing and pricing lives in the tested Python CLI; this module only calls it
const MARKED_TOOLS = new Set(['Skill', 'Agent'])
const PANE = 'tokscope'
const PANE_KEY = 'pane'
// cobalt = main thread, amber = subagents: the same two series colors as the HTML report
const MAIN = '#0398cd'
const AGENT = '#c68206'

const TURNS_SHOWN = 8
const RUNS_SHOWN = 8
const MAX_WIDTH = 72
const LABEL = 10  // 'subagents' + one space
const TURN_BAR = 16
const LIST_BAR = 10
// one glyph per call kind, so a glance tells which kinds a turn used
const KINDS = [
  { key: 'agents', glyph: '◆', label: 'subagents', color: AGENT, estimated: false },
  { key: 'mcp', glyph: '●', label: 'MCP', color: MAIN, estimated: true },
  { key: 'tools', glyph: '▸', label: 'tools', color: undefined, estimated: true },
] as const

// motion: a refresh counts the numbers up over TWEEN_MS and lights the new turn for GLOW_MS
const SPIN = '⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
const SPIN_MS = 80
const FRAME_MS = 40
const TWEEN_MS = 700
const GLOW_MS = 4000
const SPARK = '▁▂▃▄▅▆▇█'
const SPARK_TURNS = 24
const GOOD = '#2fa66a'

const view = atom({ plugin: 'tokscope', key: 'view' } as const, null as SessionView | null)
const motion = atom({ plugin: 'tokscope', key: 'motion' } as const,
  { busy: false, frame: 0, from: null, t: 1, delta: 0, fresh: null, glow: false } as Motion)
// timers are per module load; a reload cancels them with the old module
let spinner: Timer | undefined
let tween: Timer | undefined
let glow: Timer | undefined

type MarkedInput = { skill?: string; subagent_type?: string; description?: string }

function fmt(v: number | undefined): string {
  const n = v ?? 0
  for (const [unit, div] of [['B', 1e9], ['M', 1e6], ['K', 1e3]] as const) if (n >= div) return `${(n / div).toFixed(1)}${unit}`
  return String(Math.round(n))
}

// [filled, empty] cell counts; a non-zero value always gets at least one cell
function cells(value: number, top: number, size: number): [number, number] {
  const n = value > 0 ? Math.max(1, Math.round((size * value) / Math.max(top, 1))) : 0
  return [Math.min(n, size), size - Math.min(n, size)]
}

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? '' : 's'}`
}

function rule(title: string, width: number): string {
  return `── ${title} ${'─'.repeat(Math.max(2, width - title.length - 4))}`
}

function clip(text: string, width: number): string {
  return text.length > width ? `${text.slice(0, width - 1)}…` : text
}

// subagent tokens are measured; MCP/tool tokens are the size of what the call put into the context, hence "~"
function calls(items: Call[], width: number, estimated: boolean): string {
  const one = ([name, n, tokens]: Call) =>
    `${n > 1 ? `${name}×${n}` : name}${tokens ? ` ${estimated ? '~' : ''}${fmt(tokens)}` : ''}`
  return clip(items.map(one).join(' · '), width)
}

async function isOn($: EngineInterface): Promise<boolean> {
  return (await $.store.get(PANE_KEY)) === true
}

// ease-out cubic: fast start, soft landing
function ease(t: number): number {
  return 1 - (1 - Math.min(1, Math.max(0, t))) ** 3
}

function totalsOf(v: SessionView | null): Totals | null {
  return v && !v.empty && !v.error ? { tokens: v.tokens ?? 0, usd: v.usd ?? 0, main: v.main ?? 0, agents: v.agents ?? 0 } : null
}

// tokens per turn, oldest first, as block glyphs scaled to the busiest turn
function spark(turns: Turn[]): string {
  const vals = turns.slice(0, SPARK_TURNS).map(t => t.in + t.out).reverse()
  const top = Math.max(...vals, 1)
  return vals.map(n => SPARK[Math.min(SPARK.length - 1, Math.round(((SPARK.length - 1) * n) / top))]).join('')
}

async function setBusy($: EngineInterface, busy: boolean): Promise<void> {
  spinner?.cancel()
  spinner = undefined
  await update($, motion, m => ({ ...m, busy }))
  if (busy) spinner = $.clock.every(SPIN_MS, () => void update($, motion, m => ({ ...m, frame: m.frame + 1 })))
}

// counts the numbers up from what the pane showed before (from zero on first open) and lights the new turn
async function animate($: EngineInterface, from: Totals | null, to: SessionView, prevLatest: number | undefined): Promise<void> {
  tween?.cancel()
  glow?.cancel()
  const latest = to.turns?.[0]?.i
  const fresh = latest !== undefined && latest !== prevLatest ? latest : null
  const delta = from ? (to.tokens ?? 0) - from.tokens : 0
  const start = await $.clock.now()
  await update($, motion, m => ({ ...m, from, t: 0, delta, fresh, glow: fresh !== null || delta > 0 }))
  tween = $.clock.every(FRAME_MS, () => void (async () => {
    const t = Math.min(1, ((await $.clock.now()) - start) / TWEEN_MS)
    if (t >= 1) tween?.cancel()
    await update($, motion, m => ({ ...m, t }))
  })())
  glow = $.clock.after(GLOW_MS, () => void update($, motion, m => ({ ...m, glow: false })))
}

const NO_CLI = 'tokscope CLI not found on PATH or in ~/.local/bin. Install it with pipx or uv (see the README), or set TOKSCOPE_CLI.'

// TOKSCOPE_CLI, else the first tokscope on PATH, else ~/.local/bin, where pipx and `uv tool install` put it
// and which is not always on the PATH Claude Code started with; '' when there is none
async function findCli($: EngineInterface): Promise<string> {
  const set = await $.env.get('TOKSCOPE_CLI')
  if (set) return set
  const dirs = ((await $.env.get('PATH')) ?? '').split(':').filter(Boolean)
  dirs.push(`${(await $.env.get('HOME')) ?? ''}/.local/bin`)
  for (const dir of dirs) if (await $.fs.exists(`${dir}/tokscope`)) return `${dir}/tokscope`
  return ''
}

async function refresh($: EngineInterface, cli: string): Promise<void> {
  if (!cli) {
    await update($, view, () => ({ id: '', empty: true, error: NO_CLI }))
    return
  }
  await setBusy($, true)
  const ran = await $.process.run([cli, 'session', await $.session.id(), '--json'])
  let next: SessionView
  try {
    next = ran.exitCode === 0 ? JSON.parse(ran.stdout) : { id: '', empty: true, error: ran.stderr.trim() || 'tokscope failed' }
  } catch {
    next = { id: '', empty: true, error: 'tokscope returned no JSON' }
  }
  let prev: SessionView | null = null
  await update($, view, old => {
    prev = old
    return { ...next, updatedAt: Date.now() }
  })
  await setBusy($, false)
  const before = prev as SessionView | null
  if (totalsOf(next)) await animate($, totalsOf(before), next, before?.turns?.[0]?.i)
}

async function openReport($: EngineInterface, cli: string): Promise<string> {
  if (!cli) return NO_CLI
  const opened = await $.process.run([cli, 'open'])
  return opened.exitCode === 0
    // the CLI prints "wrote <path>" and then "opened in <browser>"; the path is what the person needs
    ? `Report opened in the browser: ${opened.stdout.split('\n').find(l => l.startsWith('wrote '))?.slice(6) ?? 'done'}`
    : `tokscope report failed: ${opened.stderr.trim()}`
}

async function setPane($: EngineInterface, cli: string, on: boolean): Promise<string> {
  await $.store.set(PANE_KEY, on)
  if (!on) {
    await $.ui.close({ id: PANE })
    return 'tokscope pane off. Turn it back on with /tokscope pane on.'
  }
  const opened = await $.ui.open({ id: PANE, title: 'Tokens' })
  await refresh($, cli)
  return opened.isPlaced
    ? 'tokscope pane on; it updates after each turn and stays on for new sessions.'
    : `tokscope pane on, but it is not shown yet: ${opened.reason}`
}

export const register: Register = on => {
  let cli = ''

  on('session.start', async ($, e, next) => {
    cli = await findCli($)
    await $.command.register({
      name: 'tokscope',
      description: 'Token use of this session; "/tokscope pane on|off" toggles the live pane, "/tokscope open" opens the HTML report, "/tokscope skills [name]" lists skill versions',
    })
    const ran = await next(e)
    if (await isOn($)) {
      void $.ui.open({ id: PANE, title: 'Tokens' })
      await refresh($, cli)
    }

    return ran
  })

  on('command.run', { command: 'tokscope' }, async ($, e) => {
    if (!cli) cli = await findCli($)  // installed after the session started
    const [word, state] = e.args.trim().split(/\s+/)
    if (word === 'pane') {
      const want = state === 'on' ? true : state === 'off' ? false : !(await isOn($))
      return { text: await setPane($, cli, want) }
    }
    // same words as the shell CLI: `tokscope open`, `tokscope session <id>`; "report" is the old name of open
    if (word === 'open' || word === 'report') return { text: await openReport($, cli) }
    if (!cli) return { text: NO_CLI }
    if (word === 'skills') {
      const ran = await $.process.run([cli, 'skills', ...(state ? [state] : [])])
      return { text: ran.exitCode === 0 ? ran.stdout.trimEnd() : `tokscope failed: ${ran.stderr.trim()}` }
    }
    const id = word === 'session' ? state : word
    const ran = await $.process.run([cli, 'session', id || (await $.session.id())])

    return { text: ran.exitCode === 0 ? ran.stdout.trimEnd() : `tokscope failed: ${ran.stderr.trim()}` }
  })

  on('turn.complete', async ($, e, next) => {
    const ran = await next(e)
    // subagent turns end too; only the main loop's end means new numbers for the session
    if (!e.agentId && (await isOn($))) await refresh($, cli)

    return ran
  }).catch(($, e, next) => next(e))

  // closing the pane by hand turns the feature off, so it does not reopen next session
  on('ui.close', async ($, e, next) => {
    if (e.id === PANE && e.origin.kind === 'person') await $.store.set(PANE_KEY, false)

    return next(e)
  }).catch(($, e, next) => next(e))

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Button } = $.ui.resolve(e)
    const v = await read($, view)
    const m = await read($, motion)
    const width = Math.max(32, Math.min(MAX_WIDTH, (e.props.bodyColumns ?? 40) - 1))
    const spin = SPIN[m.frame % SPIN.length]
    if (!v) return <Text><Text color={MAIN}>{spin}</Text> <Text dimColor>Reading this session…</Text></Text>
    if (v.error) return <Text color="red">✗ tokscope could not read this session: {v.error}</Text>
    if (v.empty) return <Text dimColor>○ No tokens yet. Send a prompt and this pane fills in after the turn.</Text>

    // every number on screen is the tween between the last refresh and this one; at k = 1 it is the real value
    const k = ease(m.t)
    const from = m.from ?? { tokens: 0, usd: 0, main: 0, agents: 0 }
    const lerp = (a: number, b: number | undefined | null) => a + ((b ?? 0) - a) * k
    const shown = { tokens: lerp(from.tokens, v.tokens), usd: lerp(from.usd, v.usd), main: lerp(from.main, v.main), agents: lerp(from.agents, v.agents) }
    const total = Math.max((v.main ?? 0) + (v.agents ?? 0), 1)
    // the split bar sweeps in on first open, then holds its width and shifts its split
    const filledCells = m.from ? width : Math.round(width * k)
    const agentCells = shown.agents ? Math.min(filledCells, Math.max(1, Math.round((filledCells * shown.agents) / Math.max(shown.main + shown.agents, 1)))) : 0
    const updated = v.updatedAt ? new Date(v.updatedAt).toTimeString().slice(0, 5) : ''
    const share = (n: number | undefined) => `${Math.round((100 * (n ?? 0)) / total)}%`
    const turns = (v.turns ?? []).slice(0, TURNS_SHOWN)
    // bar, total and in/out fit one line only in a wide pane
    const wide = width >= 2 + TURN_BAR + 9 + 40
    const topTurn = Math.max(...turns.map(t => t.in + t.out), 1)
    const deltaText = m.glow && m.delta > 0 ? ` ▲ ${fmt(m.delta)} ` : ''
    const status = m.busy ? `${spin} updating` : `updated ${updated}`
    const head = `${fmt(shown.tokens)} tokens  $${shown.usd.toFixed(2)}${deltaText}`
    const trend = spark(v.turns ?? [])
    // owner bars use the series colors; a skill's tokens span both series, so its bars stay neutral
    const lists: [string, [string, number][], (name: string) => string | undefined][] = [
      ['By owner', v.owners ?? [], name => (name === 'main thread' ? MAIN : AGENT)],
      ['By skill', v.skills ?? [], () => undefined],
    ]

    return (
      <Box flexDirection="column">
        <Text>
          <Text bold>{fmt(shown.tokens)} tokens</Text>  <Text color={GOOD}>${shown.usd.toFixed(2)}</Text>
          {deltaText && <Text bold color="black" backgroundColor={GOOD}>{deltaText}</Text>}
          <Text color={m.busy ? MAIN : undefined} dimColor={!m.busy}>{status.padStart(Math.max(0, width - head.length))}</Text>
        </Text>
        <Text>
          <Text color={MAIN}>{'█'.repeat(filledCells - agentCells)}</Text>
          <Text color={AGENT}>{'█'.repeat(agentCells)}</Text>
          <Text dimColor>{'░'.repeat(width - filledCells)}</Text>
        </Text>
        <Text>
          <Text color={MAIN}>■</Text> main {fmt(shown.main)} <Text dimColor>{share(v.main)}</Text>{'   '}
          <Text color={AGENT}>■</Text> subagents {fmt(shown.agents)} <Text dimColor>{share(v.agents)}</Text>
        </Text>
        {v.budget?.error && <Text color="red">✗ {v.budget.error}</Text>}
        {(v.budget?.warn ?? []).map(w => (
          <Text color={w.state === 'over' ? 'red' : AGENT}>{w.state === 'over' ? '✗ OVER' : '⚠ near'} {clip(w.text, width - 8)}</Text>
        ))}
        <Text dimColor>{plural(v.prompts ?? 0, 'prompt')} · {plural(v.runs ?? 0, 'subagent run')} · $ = API-eq: a list-price estimate, not a plan bill</Text>
        {trend.length > 1 && (
          <Text>
            <Text dimColor>{'trend'.padEnd(LABEL)}</Text>
            <Text color={MAIN}>{trend.slice(0, -1)}</Text><Text color={m.glow ? GOOD : MAIN} bold>{trend.slice(-1)}</Text>
            <Text dimColor>  last {plural(trend.length, 'turn')}, newest right</Text>
          </Text>
        )}
        <Text> </Text>
        <Text dimColor>{rule('Turns · newest first', width)}</Text>
        {turns.map((t: Turn, j: number) => {
          const agentTok = t.agents.reduce((sum, a) => sum + a[2], 0)
          const turnTok = t.in + t.out
          const isFresh = t.i === m.fresh
          // bars grow in on first open; after that only the turn that just landed grows
          const [full] = cells(turnTok, topTurn, TURN_BAR)
          const grown = !m.from || isFresh ? Math.round(full * k) : full
          const [filled, empty] = [grown, TURN_BAR - grown]
          const [aFilled] = cells(Math.min(agentTok, turnTok), turnTok, filled)
          const price = t.usd == null ? 'no price' : `$${t.usd.toFixed(2)}`
          const glowing = isFresh && m.glow
          const tag = j === 0 ? (glowing ? ' NEW ' : ' latest') : ''
          const label = `#${t.i}${tag}`
          const io = `in ${fmt(t.in)} · out ${fmt(t.out)} · ${plural(t.requests, 'model call')}`
          const missing = KINDS.filter(kind => t[kind.key].length === 0).map(kind => kind.label)
          return (
            <Box flexDirection="column" marginTop={j ? 1 : 0}>
              <Text>
                <Text bold color={MAIN}>#{t.i}</Text>
                {tag && <Text bold={glowing} color={glowing ? 'black' : GOOD} backgroundColor={glowing ? GOOD : undefined}>{tag}</Text>}{' '}
                {clip(t.text || '(no text)', width - label.length - price.length - 3).padEnd(width - label.length - price.length - 2)}
                <Text dimColor={t.usd == null}>{price}</Text>
              </Text>
              <Text>
                {'  '}<Text color={MAIN}>{'█'.repeat(filled - aFilled)}</Text><Text color={AGENT}>{'█'.repeat(aFilled)}</Text>
                <Text dimColor>{'░'.repeat(empty)}</Text> <Text bold>{fmt(turnTok)}</Text>
                {wide && <Text dimColor>  {io}</Text>}
              </Text>
              {!wide && <Text dimColor>{'  '}{io}</Text>}
              {KINDS.filter(kind => t[kind.key].length > 0).map(kind => kind.key === 'agents' ? (
                <Box flexDirection="column">
                  <Text>
                    {'  '}<Text color={kind.color}>{kind.glyph} {kind.label.padEnd(LABEL)}</Text>
                    {plural(t.runs.length, 'run')} · {fmt(agentTok)}
                  </Text>
                  {t.runs.slice(0, RUNS_SHOWN).map((r: Run) => {
                    const lead = `${' '.repeat(4 + 2 * (Math.max(1, r.depth) - 1))}${r.depth > 1 ? '↳ ' : ''}`
                    const price = r.usd == null ? '' : `$${r.usd.toFixed(2)}`
                    const nums = 15  // tokens (8) + price (7)
                    const desc = r.desc || '(no description)'
                    // wide: type and description share the line; narrow: the description goes underneath
                    const typeWidth = wide ? Math.min(18, Math.max(...t.runs.map(x => x.type.length))) : width - lead.length - nums
                    const descWidth = width - lead.length - typeWidth - 1 - nums
                    return (
                      <Box flexDirection="column">
                        <Text>
                          {lead}<Text color={AGENT}>{clip(r.type, typeWidth).padEnd(typeWidth)}</Text>
                          {wide && <Text dimColor>{' '}{clip(desc, descWidth).padEnd(descWidth)}</Text>}
                          <Text bold>{fmt(r.tokens).padStart(8)}</Text><Text dimColor>{price.padStart(7)}</Text>
                        </Text>
                        {!wide && <Text dimColor>{' '.repeat(lead.length + 2)}{clip(desc, width - lead.length - 2)}</Text>}
                      </Box>
                    )
                  })}
                  {t.runs.length > RUNS_SHOWN && <Text dimColor>{'    '}+{t.runs.length - RUNS_SHOWN} more runs: /tokscope open</Text>}
                </Box>
              ) : (
                <Text>
                  {'  '}<Text color={kind.color}>{kind.glyph} {kind.label.padEnd(LABEL)}</Text>
                  {calls(t[kind.key], width - LABEL - 4, kind.estimated)}
                </Text>
              ))}
              {missing.length > 0 && (
                <Text dimColor>{'  '}{missing.length === KINDS.length ? 'no calls: answered directly' : `no ${missing.join(', no ')}`}</Text>
              )}
            </Box>
          )
        })}
        {(v.turns ?? []).length > TURNS_SHOWN && <Text dimColor>{(v.turns ?? []).length - TURNS_SHOWN} older turns: /tokscope</Text>}
        {turns.length > 0 && <Text dimColor>~ = estimated from the size of the result</Text>}
        {lists.filter(([, rows]) => rows.length > 0).map(([title, rows, colorOf]) => {
          const top = Math.max(...rows.map(r => r[1]), 1)
          const nameWidth = width - LIST_BAR - 10
          return (
            <Box flexDirection="column" marginTop={1}>
              <Text dimColor>{rule(title, width)}</Text>
              {rows.map(([name, tok]) => {
                const [f, e2] = cells(tok, top, LIST_BAR)
                return (
                  <Text>
                    {clip(name, nameWidth).padEnd(nameWidth)} <Text color={colorOf(name)}>{'█'.repeat(f)}</Text>
                    <Text dimColor>{'░'.repeat(e2)}</Text>{fmt(tok).padStart(8)}
                  </Text>
                )
              })}
            </Box>
          )
        })}
        <Box marginTop={1} gap={2}>
          <Button key="refresh" hotkey="r" dimColor={m.busy} onPress={() => refresh($, cli)}>{m.busy ? `${spin} Refreshing` : '↻ Refresh'}</Button>
          <Button key="report" hotkey="o" onPress={async () => { $.ui.toast(await openReport($, cli)) }}>↗ Open report</Button>
        </Box>
      </Box>
    )
  })

  // tool.call, not classic.PostToolUse: the built-in sec-default plugin sends classic.* past user mods.
  // tool_use_id joins a mark to OTel's tool_result event, which carries prompt.id.
  on('tool.call', async ($, e, next) => {
    if (!MARKED_TOOLS.has(e.tool)) return next(e)
    const startedAt = await $.clock.now()
    const ran = await next(e)
    const input = e as unknown as MarkedInput
    const mark = {
      kind: 'tool', session_id: await $.session.id(), agent_id: e.agentId, tool: e.tool,
      tool_use_id: e.tool_use_id, skill: input.skill, subagent_type: input.subagent_type,
      // the CLI finds the skill's folder from here (project skills live under the session's directory)
      cwd: await $.session.cwd(),
      description: input.description, duration_ms: (await $.clock.now()) - startedAt,
      is_error: ran.isError === true || ran.deny !== undefined,
    }
    if (cli) await $.process.run([cli, 'mark'], { stdin: JSON.stringify(mark) + '\n' })

    return ran
  }).catch(($, e, next) => next(e))

  on('session.end', async ($, e, next) => {
    if (cli) {
      const ran = await $.process.run([cli, 'ingest', '--session', e.sessionId])
      // the CLI prints one "tokscope budget:" line when this session pushed a budget to near or over
      const line = ran.stdout.split('\n').find(l => l.startsWith('tokscope budget:'))
      if (line) $.ui.toast(line)
    }

    return next(e)
  })
}
