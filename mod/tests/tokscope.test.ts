import { expect, mock, test } from 'claude-code/testing'

type Run = { argv: readonly string[]; init?: { stdin?: string } }

const VIEW = {
  id: 'live-session', empty: false, title: 't', prompts: 3, tokens: 4_200_000, output: 9_000, usd: 1.5,
  main: 4_000_000, agents: 200_000, runs: 1, owners: [['main thread', 4_000_000], ['reviewer', 200_000]],
  skills: [['writing-plans', 1_000_000]], last: { i: 3, text: 'review the diff', tokens: 900_000, agents: 200_000 },
  turns: [
    { i: 3, text: 'review the diff', in: 880_000, out: 20_000, usd: 0.75, requests: 9, agents: [['reviewer', 2, 300_000]],
      runs: [{ type: 'reviewer', desc: 'Correctness review', depth: 1, tokens: 200_000, out: 3_000, usd: 0.12, model: 'opus-5-5' },
             { type: 'correctness-scorer', desc: 'Score finding 1', depth: 2, tokens: 100_000, out: 1_000, usd: null, model: 'sonnet-5-5' }],
      mcp: [['datadog', 4, 25_000]], tools: [['Bash', 3, 1_200], ['ToolSearch', 1, 0]] },
    { i: 2, text: 'what is this', in: 50_000, out: 1_000, usd: null, requests: 1, agents: [], runs: [], mcp: [], tools: [] },
  ],
}

const PANE = {
  plugin: 'tokscope', component: 'Pane', requestId: 'tokscope', surface: 'terminal',
  props: { title: 'Tokens', isFocused: false, bodyColumns: 40, placement: 'dock', scroll: { offset: 0, bodyRows: 30 }, view: {} },
} as const

async function start($: Parameters<Parameters<typeof test>[1]>[0], on: Parameters<Parameters<typeof test>[1]>[1],
                     opts: { exitCode?: number; paneOn?: boolean; env?: Record<string, string>; source?: { view: unknown }; files?: string[] } = {}) {
  const runs: Run[] = []
  const store: Record<string, unknown> = opts.paneOn ? { pane: true } : {}
  const panes: string[] = []
  const env: Record<string, string> = { HOME: '/home/u', ...opts.env }
  on('env.get', (_, e) => ({ value: env[e.name] }))
  const files = opts.files ?? ['/home/u/.local/bin/tokscope']
  on('fs.exists', (_, e) => ({ value: files.includes(e.path) }))
  on('session.id', () => ({ value: 'live-session' }))
  on('session.cwd', () => ({ value: '/home/u/work/app' }))
  on('command.register', () => ({ value: { command: 'tokscope' } }))
  on('store.get', (_, e) => ({ value: store[e.key] }))
  on('store.set', (_, e) => { store[e.key] = e.value; return { value: undefined } })
  on('ui.open', (_, e) => { panes.push(`open:${e.id}`); return { value: { isPlaced: true } } })
  on('ui.close', (_, e) => { panes.push(`close:${e.id}`); return { value: undefined } })
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('session.end', (_, e) => ({ sessionId: e.sessionId }))
  on('turn.complete', () => ({ text: '' }))
  on('tool.call', () => ({ result: {} }))
  const clock = mock.clock(on, { now: 1000 })
  on('process.run', (_, e) => {
    runs.push(e)
    const json = e.argv.includes('--json')
    const out = json ? JSON.stringify(opts.source?.view ?? VIEW)
      : e.argv[1] === 'open' ? 'wrote /home/u/.local/share/tokscope/reports/report.html\nopened in google-chrome\n' : 'tokscope · $1.00\n'
    return { value: { exitCode: opts.exitCode ?? 0, stdout: out,
                      stderr: opts.exitCode ? 'boom' : '', isStdoutTruncated: false } }
  })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })

  return { runs, store, panes, clock }
}

const sessionRuns = (runs: Run[]) => runs.filter(r => r.argv[1] === 'session')

test('the pane is off by default: no pane opens and turns run no CLI', async ($, on) => {
  const { runs, panes } = await start($, on)

  await $.turn.complete({ answer: 'x', durationMs: 1, isAborted: false, turnId: 't1', reason: 'answer' })

  expect(panes).toEqual([])
  expect(sessionRuns(runs)).toEqual([])
})

test('/tokscope pane on opens the pane, remembers it, and refreshes after each main-loop turn', async ($, on) => {
  const { runs, store, panes } = await start($, on)

  const text = (await $.command.run({ command: 'tokscope', args: 'pane on' })).text
  await $.turn.complete({ answer: 'x', durationMs: 1, isAborted: false, turnId: 't1', reason: 'answer' })
  await $.turn.complete({ answer: 'x', durationMs: 1, isAborted: false, turnId: 't2', reason: 'answer', agentId: 'a1' })

  expect(text).toContain('pane on')
  expect(store.pane).toBe(true)
  expect(panes).toEqual(['open:tokscope'])
  // one refresh on enable, one for the main turn; the subagent's turn end does not refresh
  expect(sessionRuns(runs).map(r => r.argv.slice(1))).toEqual([
    ['session', 'live-session', '--json'], ['session', 'live-session', '--json']])
})

test('/tokscope pane off closes it and turns stop refreshing', async ($, on) => {
  const { runs, store, panes } = await start($, on, { paneOn: true })

  await $.command.run({ command: 'tokscope', args: 'pane off' })
  const before = sessionRuns(runs).length
  await $.turn.complete({ answer: 'x', durationMs: 1, isAborted: false, turnId: 't1', reason: 'answer' })

  expect(store.pane).toBe(false)
  expect(panes).toContain('close:tokscope')
  expect(sessionRuns(runs).length).toBe(before)
})

test('a session starts with the pane open when it was left on', async ($, on) => {
  const { panes, runs } = await start($, on, { paneOn: true })

  expect(panes).toEqual(['open:tokscope'])
  expect(sessionRuns(runs).length).toBe(1)
})

test('each turn shows its tokens, price, model calls, and which subagents, MCP servers and tools it used', async ($, on) => {
  const { clock } = await start($, on)
  await $.command.run({ command: 'tokscope', args: 'pane on' })
  await clock.advance(5000)

  const ui = await $.ui.mount(PANE)

  // a narrow pane puts in/out under the bar instead of wrapping it
  expect(await ui.find({ type: 'Text', text: /^\s+█+\s900\.0K$/ })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: /^\s+in 880\.0K · out 20\.0K · 9 model calls$/ })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: /1 model call$/ })).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /#3 latest/ }))?.text).toContain('$0.75')
  // subagent tokens are measured, MCP and tool tokens estimated (~)
  // every subagent run gets its own line: type, what it was asked, tokens, price; nested runs are indented
  expect(await ui.find({ type: 'Text', text: /◆ subagents\s+2 runs · 300\.0K/ })).toBeTruthy()
  // the 40-column test pane is narrow: the description sits under the type
  expect(await ui.find({ type: 'Text', text: /^ {4}reviewer\s+200\.0K\s+\$0\.12$/ })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: /^ {6}Correctness review$/ })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: /^ {6}↳ correctness-sco…\s+100\.0K\s*$/ })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: /^ {10}Score finding 1$/ })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: /reviewer×2/ })).toBeFalsy()
  expect(await ui.find({ type: 'Text', text: /● MCP\s+datadog×4 ~25\.0K/ })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: /▸ tools\s+Bash×3 ~1\.2K · ToolSearch$/ })).toBeTruthy()
  // a turn without calls says so once, and an unknown model shows no price instead of $0.00
  expect(await ui.find({ type: 'Text', text: /no calls: answered directly/ })).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /what is this/ }))?.text).toContain('no price')
  await ui.unmount()
})

test('a wide pane keeps the bar, total and in/out of a turn on one line', async ($, on) => {
  const { clock } = await start($, on)
  await $.command.run({ command: 'tokscope', args: 'pane on' })
  await clock.advance(5000)

  const ui = await $.ui.mount({ ...PANE, props: { ...PANE.props, bodyColumns: 80 } })

  expect(await ui.find({ type: 'Text', text: /█+ 900\.0K\s+in 880\.0K · out 20\.0K · 9 model calls$/ })).toBeTruthy()
  // a wide pane keeps type, description, tokens and price of a run on one line
  expect(await ui.find({ type: 'Text', text: /^ {4}reviewer\s+Correctness review\s+200\.0K\s+\$0\.12$/ })).toBeTruthy()
  await ui.unmount()
})

test('the pane shows the totals, both series with their share, and owner bars', async ($, on) => {
  const { clock } = await start($, on)
  await $.command.run({ command: 'tokscope', args: 'pane on' })
  await clock.advance(5000)

  const ui = await $.ui.mount(PANE)

  expect((await ui.find({ type: 'Text', text: /4\.2M tokens/ }))?.text).toContain('$1.50')
  expect(await ui.find({ type: 'Text', text: /main 4\.0M 95%/ })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: /subagents 200\.0K 5%/ })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: /3 prompts · 1 subagent run ·/ })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: /^reviewer\s+█░+\s+200\.0K$/ })).toBeTruthy()
  await ui.unmount()
})

test('totals count up from zero on open, then land on the real value', async ($, on) => {
  const { clock } = await start($, on)
  await $.command.run({ command: 'tokscope', args: 'pane on' })
  await clock.advance(120)

  const mid = await $.ui.mount(PANE)
  const midText = (await mid.find({ type: 'Text', text: /tokens\s+\$/ }))?.text ?? ''
  await mid.unmount()
  await clock.advance(5000)
  const done = await $.ui.mount(PANE)

  // part way through the tween the pane shows less than the total, never more
  expect(midText).not.toContain('4.2M tokens')
  expect(midText).toMatch(/tokens/)
  expect((await done.find({ type: 'Text', text: /4\.2M tokens/ }))?.text).toContain('$1.50')
  await done.unmount()
})

test('a refresh with a new turn shows the token delta and a NEW badge that fades to latest', async ($, on) => {
  const source: { view: unknown } = { view: VIEW }
  const { clock } = await start($, on, { source })
  await $.command.run({ command: 'tokscope', args: 'pane on' })
  await clock.advance(5000)
  // the next refresh sees one turn more and 100K more tokens than the one before
  source.view = { ...VIEW, tokens: 4_300_000, turns: [{ ...VIEW.turns[0], i: 4 }, ...VIEW.turns] }
  await $.turn.complete({ answer: 'x', durationMs: 1, isAborted: false, turnId: 't1', reason: 'answer' })
  await clock.advance(1000)

  const lit = await $.ui.mount(PANE)
  expect(await lit.find({ type: 'Text', text: /▲ 100\.0K/ })).toBeTruthy()
  expect(await lit.find({ type: 'Text', text: /#4 NEW/ })).toBeTruthy()
  await lit.unmount()
  await clock.advance(5000)

  const calm = await $.ui.mount(PANE)
  expect(await calm.find({ type: 'Text', text: /▲/ })).toBeFalsy()
  expect(await calm.find({ type: 'Text', text: /#4 latest/ })).toBeTruthy()
  await calm.unmount()
})

test('the trend line draws one glyph per turn, scaled to the busiest', async ($, on) => {
  const { clock } = await start($, on)
  await $.command.run({ command: 'tokscope', args: 'pane on' })
  await clock.advance(5000)

  const ui = await $.ui.mount(PANE)

  // oldest (50K) left, newest (900K) right
  expect(await ui.find({ type: 'Text', text: /^trend\s+▁█\s+last 2 turns/ })).toBeTruthy()
  await ui.unmount()
})

test('the pane buttons refresh the numbers and open the report', async ($, on) => {
  const { runs, clock } = await start($, on)
  await $.command.run({ command: 'tokscope', args: 'pane on' })
  await clock.advance(5000)
  const ui = await $.ui.mount(PANE)
  const before = sessionRuns(runs).length

  await ui.press({ key: 'refresh' })
  await ui.press({ key: 'report' })

  expect(sessionRuns(runs).length).toBe(before + 1)
  expect(runs.some(r => r.argv.join(' ') === '/home/u/.local/bin/tokscope open')).toBe(true)
  await ui.unmount()
})

test('/tokscope open rebuilds the HTML report and opens it', async ($, on) => {
  const { runs } = await start($, on)
  const out = await $.command.run({ command: 'tokscope', args: 'open' })

  expect(runs.some(r => r.argv.join(' ') === '/home/u/.local/bin/tokscope open')).toBe(true)
  expect(out.text).toBe('Report opened in the browser: /home/u/.local/share/tokscope/reports/report.html')
})

test('TOKSCOPE_CLI points the mod at another CLI, and the old "report" word still opens it', async ($, on) => {
  const { runs } = await start($, on, { env: { TOKSCOPE_CLI: '/opt/tokscope/bin/tokscope' } })
  await $.command.run({ command: 'tokscope', args: 'report' })

  expect(runs.some(r => r.argv.join(' ') === '/opt/tokscope/bin/tokscope open')).toBe(true)
})

test('a CLI failure shows in the pane instead of stale numbers', async ($, on) => {
  const { clock } = await start($, on, { exitCode: 1 })
  await $.command.run({ command: 'tokscope', args: 'pane on' })
  await clock.advance(5000)

  const ui = await $.ui.mount(PANE)

  expect((await ui.find({ type: 'Text', text: /boom/ }))?.text).toBe('✗ tokscope could not read this session: boom')
  await ui.unmount()
})

test('/tokscope prints the CLI breakdown of the live session, or of the id given', async ($, on) => {
  const { runs } = await start($, on)

  expect((await $.command.run({ command: 'tokscope', args: '' })).text).toBe('tokscope · $1.00')
  await $.command.run({ command: 'tokscope', args: ' other-id ' })
  await $.command.run({ command: 'tokscope', args: 'session third-id' })

  expect(sessionRuns(runs).map(r => r.argv.slice(1))).toEqual([['session', 'live-session'], ['session', 'other-id'], ['session', 'third-id']])
})

test('Skill and Agent calls are marked with the session directory, so the CLI can hash that skill; other tools are not', async ($, on) => {
  const { runs } = await start($, on)

  await $.tool.call({ tool: 'Skill', skill: 'writing-plans', tool_use_id: 't1' })
  await $.tool.call({ tool: 'Read', file_path: '/x', tool_use_id: 't3' })

  const marks = runs.filter(r => r.argv[1] === 'mark').map(r => JSON.parse(r.init?.stdin ?? '{}'))
  expect(marks).toHaveLength(1)
  expect(marks[0]).toMatchObject({ tool: 'Skill', skill: 'writing-plans', tool_use_id: 't1', cwd: '/home/u/work/app' })
})

test('the session is ingested when it ends', async ($, on) => {
  const { runs } = await start($, on)

  await $.session.end({ reason: 'prompt_input_exit', sessionId: 'ended', resume: { sessionId: 'ended' } as never })

  expect(runs.filter(r => r.argv[1] === 'ingest').map(r => r.argv.slice(1))).toEqual([['ingest', '--session', 'ended']])
})

test('the CLI is found on PATH before ~/.local/bin', async ($, on) => {
  const { runs } = await start($, on, { env: { PATH: '/usr/bin:/opt/uv/bin' },
                                        files: ['/opt/uv/bin/tokscope', '/home/u/.local/bin/tokscope'] })
  await $.command.run({ command: 'tokscope', args: 'open' })

  expect(runs.map(r => r.argv[0])).toContain('/opt/uv/bin/tokscope')
  expect(runs.map(r => r.argv[0])).not.toContain('/home/u/.local/bin/tokscope')
})

test('with no CLI installed, the command and the pane say how to install it and nothing runs', async ($, on) => {
  const { runs } = await start($, on, { files: [] })

  expect((await $.command.run({ command: 'tokscope', args: '' })).text).toContain('tokscope CLI not found')
  await $.command.run({ command: 'tokscope', args: 'pane on' })
  const ui = await $.ui.mount(PANE)
  expect((await ui.find({ type: 'Text', text: /CLI not found/ }))?.text).toContain('pipx or uv')
  expect(runs).toEqual([])
})

test('/tokscope skills lists skill versions, for one skill when named', async ($, on) => {
  const { runs } = await start($, on)
  await $.command.run({ command: 'tokscope', args: 'skills' })
  await $.command.run({ command: 'tokscope', args: 'skills correctness-review' })

  expect(runs.filter(r => r.argv[1] === 'skills').map(r => r.argv.slice(1))).toEqual([['skills'], ['skills', 'correctness-review']])
  expect(sessionRuns(runs)).toEqual([])
})
