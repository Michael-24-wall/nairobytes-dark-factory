import { useEffect, useMemo, useState } from 'react'
import { NavLink, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import {
  Activity, AlertTriangle, ArrowUpRight, Beaker, BookOpen, Check, ChevronRight,
  CircleHelp, Clock3, Copy, Database, FileCheck2, FlaskConical, Gauge, GitBranch,
  HardDrive, Layers3, LockKeyhole, Menu, Play, Plus, RefreshCw, Server, Settings2,
  ShieldCheck, Sparkles, TerminalSquare, X, Zap,
} from 'lucide-react'
import { apiBaseUrl } from './api/client'
import { createReservation, createReservationWithStatus, createTable, getReservation } from './api/reservations'
import { evidenceItems } from './data/evidence'

const stages = [
  ['ARCHITECT', 'Plan + invariants', 'PASS', 'Requirements, data model, risks, acceptance tasks.'],
  ['BUILDER', 'Implementation', 'PASS', 'FastAPI, PostgreSQL, API tests, and frontend integration.'],
  ['BREAKER', 'Adversarial testing', 'PASS', 'Concurrency, idempotency, timezone, and constraint attacks.'],
  ['REPAIR', 'Root-cause repair', 'NOT REQUIRED', 'No new defect found in the final factory simulation.'],
  ['RETEST', 'Focused confirmation', 'NOT REQUIRED', 'Breaker repetitions held on the verified baseline.'],
  ['VERIFIER', 'Independent validation', 'PASS', '46 tests passed with one non-failing warning.'],
  ['HUMAN', 'Final acceptance', 'PENDING', 'The final decision remains with a human.'],
]

const navItems = [
  ['/', 'Dashboard', Gauge],
  ['/factory', 'Factory Run', GitBranch],
  ['/reservations', 'Reservation Lab', Layers3],
  ['/idempotency', 'Idempotency Lab', LockKeyhole],
  ['/timezone', 'Timezone Lab', Clock3],
  ['/agents', 'Agent Pipeline', Sparkles],
  ['/evidence', 'Evidence Center', FileCheck2],
  ['/health', 'System Health', Activity],
  ['/about', 'About Factory', BookOpen],
]

const defaultReservation = {
  customer_name: 'Factory observer',
  table_id: 't1',
  start_time: '2026-06-01T18:00:00+00:00',
  end_time: '2026-06-01T19:00:00+00:00',
  idempotency_key: '',
}

function App() {
  const [backendStatus, setBackendStatus] = useState('CHECKING')
  const [mobileNav, setMobileNav] = useState(false)

  useEffect(() => {
    let active = true
    fetch(`${apiBaseUrl}/docs`, { signal: AbortSignal.timeout(4000) })
      .then((response) => { if (active) setBackendStatus(response.status < 500 ? 'ONLINE' : 'DEGRADED') })
      .catch(() => { if (active) setBackendStatus('OFFLINE') })
    return () => { active = false }
  }, [])

  return (
    <div className="app-shell">
      <aside className={`sidebar ${mobileNav ? 'sidebar-open' : ''}`}>
        <div className="brand">
          <div className="brand-mark"><span /><span /><span /></div>
          <div><strong>NAIROBYTES</strong><small>DARK FACTORY</small></div>
        </div>
        <div className="sidebar-label">OPERATIONS CONSOLE</div>
        <nav className="nav-list" aria-label="Primary navigation">
          {navItems.map(([path, label, Icon]) => (
            <NavLink key={path} to={path} end={path === '/'} onClick={() => setMobileNav(false)} className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
              <Icon size={17} strokeWidth={1.8} /><span>{label}</span>{path === '/reservations' && <span className="nav-dot" />}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-footer">
          <div className="live-chip"><span className="pulse-dot" /> {backendStatus === 'ONLINE' ? 'API CONNECTED' : `API ${backendStatus}`}</div>
          <div className="version-row"><span>v1.0.0</span><span>LOCAL</span></div>
        </div>
      </aside>
      {mobileNav && <button className="mobile-backdrop" aria-label="Close navigation" onClick={() => setMobileNav(false)} />}
      <main className="main-area">
        <header className="topbar">
          <button className="menu-toggle" aria-label="Open navigation" onClick={() => setMobileNav(true)}><Menu size={20} /></button>
          <div className="breadcrumb"><span>FACTORY CONTROL</span><ChevronRight size={14} /><PageCrumb /></div>
          <div className="topbar-right">
            <span className="run-tag"><span className="pulse-dot" /> RUN 2026.10.02</span>
            <span className="topbar-divider" />
            <span className={`system-state ${backendStatus === 'ONLINE' ? 'good' : ''}`}><span /> {backendStatus === 'CHECKING' ? 'CHECKING SYSTEM' : `BACKEND ${backendStatus}`}</span>
          </div>
        </header>
        <div className="page-wrap"><Routes><Route path="/" element={<Dashboard backendStatus={backendStatus} />} /><Route path="/factory" element={<FactoryRun />} /><Route path="/reservations" element={<ReservationLab />} /><Route path="/idempotency" element={<IdempotencyLab />} /><Route path="/timezone" element={<TimezoneLab />} /><Route path="/agents" element={<AgentPipeline />} /><Route path="/evidence" element={<EvidenceCenter />} /><Route path="/health" element={<Health backendStatus={backendStatus} />} /><Route path="/about" element={<About />} /><Route path="*" element={<Dashboard backendStatus={backendStatus} />} /></Routes></div>
      </main>
    </div>
  )
}

function PageCrumb() {
  const location = useLocation()
  return <strong>{navItems.find(([path]) => path === location.pathname)?.[1]?.toUpperCase() || 'DASHBOARD'}</strong>
}

function PageHeading({ eyebrow, title, detail, action }) {
  return <div className="page-heading"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1>{detail && <p>{detail}</p>}</div>{action}</div>
}

function StatusBadge({ status }) {
  const normalized = status.toLowerCase().replaceAll(' ', '-')
  return <span className={`status-badge ${normalized}`}><span />{status}</span>
}

function MetricCard({ label, value, detail, icon: Icon, tone = 'mint' }) {
  return <div className="metric-card"><div className={`metric-icon ${tone}`}><Icon size={17} /></div><div className="metric-copy"><span>{label}</span><strong>{value}</strong><small>{detail}</small></div></div>
}

function Pipeline({ compact = false }) {
  return <div className={`pipeline ${compact ? 'compact' : ''}`}>{stages.map(([name, role, status], index) => <div className="pipeline-step" key={name}><div className={`pipeline-node ${status.toLowerCase().replaceAll(' ', '-')}`}>{status === 'PASS' ? <Check size={16} /> : status === 'PENDING' ? <CircleHelp size={16} /> : <span>{index + 1}</span>}</div><div><strong>{name}</strong><small>{role}</small></div>{index < stages.length - 1 && <div className="pipeline-line" />}</div>)}</div>
}

function Dashboard({ backendStatus }) {
  return <>
    <PageHeading eyebrow="FACTORY OVERVIEW / RECORDED RUN" title="The system held." detail="A verified reservation engine, observed through the factory lens." action={<button className="quiet-button" onClick={() => window.location.reload()}><RefreshCw size={15} /> Refresh status</button>} />
    <section className="hero-status"><div className="hero-orbit"><div className="orbit-ring ring-one" /><div className="orbit-ring ring-two" /><ShieldCheck size={31} /></div><div className="hero-status-copy"><span className="section-kicker">LATEST VERIFIED STATE</span><h2>Verified / Ready for acceptance</h2><p>46 tests passed across schema, API, concurrency, idempotency, and timezone behavior.</p><div className="hero-meta"><span><span className="pulse-dot" /> RECORDED EVIDENCE</span><span>RUN 2026.10.02</span><span>POSTGRESQL / 5439</span></div></div><div className="hero-score"><strong>46<span>/46</span></strong><small>TESTS PASSED</small></div></section>
    <div className="metrics-grid"><MetricCard label="Tests passed" value="46 / 46" detail="Full suite · verified" icon={Check} /><MetricCard label="Warnings" value="01" detail="Non-failing deprecation" icon={AlertTriangle} tone="amber" /><MetricCard label="Concurrency" value="0" detail="Overlapping pairs" icon={Zap} /><MetricCard label="API status" value={backendStatus === 'ONLINE' ? 'ONLINE' : backendStatus} detail="Measured from browser" icon={Server} tone="blue" /></div>
    <section className="content-section"><div className="section-title"><div><span className="section-kicker">THE FACTORY LINE</span><h2>Seven gates to acceptance</h2></div><NavLink to="/factory" className="text-link">Open run detail <ArrowUpRight size={15} /></NavLink></div><Pipeline /></section>
    <section className="two-column"><div className="panel activity-panel"><div className="panel-heading"><div><span className="section-kicker">RECENT ACTIVITY</span><h3>Evidence timeline</h3></div><StatusBadge status="RECORDED" /></div><ActivityRow icon={ShieldCheck} title="Verifier completed full suite" detail="46 passed · 1 warning" time="Recorded" /><ActivityRow icon={Beaker} title="Breaker attack held" detail="overlapping_pair_count = 0" time="Recorded" /><ActivityRow icon={LockKeyhole} title="Concurrency protection verified" detail="Advisory lock + GiST exclusion" time="Recorded" /></div><div className="panel principle-panel"><span className="section-kicker">FACTORY PRINCIPLE</span><h3>Make it. Attack it. Prove it.</h3><p>AI agents do not simply generate code. They produce software, challenge it, repair it, and prove it.</p><NavLink to="/about" className="outline-link">Read the method <ChevronRight size={15} /></NavLink></div></section>
  </>
}

function ActivityRow({ icon: Icon, title, detail, time }) { return <div className="activity-row"><div className="activity-icon"><Icon size={16} /></div><div><strong>{title}</strong><small>{detail}</small></div><span>{time}</span></div> }

function FactoryRun() {
  return <><PageHeading eyebrow="FACTORY RUN / 2026.10.02" title="A recorded execution" detail="Every stage is visible. Nothing here implies live agent activity." action={<StatusBadge status="VERIFIED" />} /><section className="run-summary"><div><span className="section-kicker">OBJECTIVE</span><h2>Validate a reservation system under pressure.</h2><p>Schema integrity, time correctness, idempotent retries, and concurrent booking behavior were tested against PostgreSQL.</p></div><div className="run-facts"><span><small>CURRENT STAGE</small><strong>HUMAN ACCEPTANCE</strong></span><span><small>AGENT ACTIVITY</small><strong>RECORDED</strong></span><span><small>DATABASE</small><strong>POSTGRESQL · 5439</strong></span></div></section><section className="content-section"><div className="section-title"><div><span className="section-kicker">EXECUTION GRAPH</span><h2>From objective to proof</h2></div></div><div className="large-pipeline">{stages.map(([name, role, status, description], index) => <div className={`run-stage ${status === 'PASS' ? 'stage-pass' : status === 'PENDING' ? 'stage-pending' : ''}`} key={name}><div className="run-stage-index">0{index + 1}</div><div className="run-stage-main"><div><strong>{name}</strong><span>{role}</span></div><p>{description}</p></div><StatusBadge status={status} />{index < stages.length - 1 && <div className="vertical-connector" />}</div>)}</div></section><section className="two-column"><div className="panel"><div className="panel-heading"><div><span className="section-kicker">OUTPUTS</span><h3>Evidence generated</h3></div></div><EvidenceMini name="factory_final_verification.md" detail="Final stage matrix" /><EvidenceMini name="breaker_concurrency.md" detail="Repeated attack results" /><EvidenceMini name="final_test_run.txt" detail="46 test execution log" /></div><div className="panel callout-panel"><TerminalSquare size={20} /><h3>Recorded, not live</h3><p>This run is grounded in files under <code>evidence/</code>. Live backend calls are available in the Reservation Lab.</p><NavLink to="/evidence" className="outline-link">Browse evidence <ArrowUpRight size={15} /></NavLink></div></section></>
}

function EvidenceMini({ name, detail }) { return <div className="evidence-mini"><FileCheck2 size={16} /><div><strong>{name}</strong><small>{detail}</small></div><StatusBadge status="PASS" /></div> }

function ReservationLab() {
  const [form, setForm] = useState({ ...defaultReservation, idempotency_key: `ui-${crypto.randomUUID?.() || Date.now()}` })
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [tableMessage, setTableMessage] = useState('')
  const [attack, setAttack] = useState({ count: 8, running: false, result: null })
  const update = (key, value) => setForm((current) => ({ ...current, [key]: value }))
  const submit = async (event) => { event.preventDefault(); setBusy(true); setError(null); setResult(null); try { setResult(await createReservation(form)) } catch (err) { setError(formatApiError(err)) } finally { setBusy(false) } }
  const provision = async (tableId) => { setTableMessage(`Creating ${tableId}...`); try { await createTable({ table_id: tableId, capacity: 4 }); setTableMessage(`${tableId} is ready.`) } catch (err) { setTableMessage(err.code === 'TABLE_EXISTS' ? `${tableId} already exists.` : formatApiError(err)) } }
  const runAttack = async () => { setAttack((current) => ({ ...current, running: true, result: null })); const key = `attack-${crypto.randomUUID?.() || Date.now()}`; const payload = { ...form, table_id: form.table_id, idempotency_key: key }; const count = Math.max(2, Math.min(25, Number(attack.count) || 8)); const responses = await Promise.all(Array.from({ length: count }, () => createReservationWithStatus(payload).then((response) => ({ status: response.status, body: response.data })).catch((err) => ({ status: err.status || 0, error: err })))) ; const summary = { sent: count, success: responses.filter((item) => item.status === 201).length, replay: responses.filter((item) => item.status === 200).length, conflicts: responses.filter((item) => item.status === 409).length, failed: responses.filter((item) => item.status === 0 || item.status >= 500).length, responses }; setAttack({ count, running: false, result: summary }) }
  return <><PageHeading eyebrow="RESERVATION LAB / LIVE API" title="Operate the engine" detail="Create real reservations against the FastAPI backend. Table provisioning and booking responses are never simulated." action={<span className="live-chip"><span className="pulse-dot" /> LIVE REQUESTS</span>} /><div className="lab-grid"><section className="panel reservation-form-panel"><div className="panel-heading"><div><span className="section-kicker">01 / RESERVATION</span><h3>Book a table</h3></div><Beaker size={19} /></div><form onSubmit={submit} className="form-grid"><Field label="Customer name" value={form.customer_name} onChange={(value) => update('customer_name', value)} /><Field label="Table ID" value={form.table_id} onChange={(value) => update('table_id', value)} /><Field label="Start time" type="text" value={form.start_time} onChange={(value) => update('start_time', value)} hint="ISO 8601 with offset" /><Field label="End time" type="text" value={form.end_time} onChange={(value) => update('end_time', value)} hint="ISO 8601 with offset" /><Field label="Idempotency key" value={form.idempotency_key} onChange={(value) => update('idempotency_key', value)} wide hint="Reuse this key to observe a real 200 replay." /><button className="primary-button wide" disabled={busy}>{busy ? <><RefreshCw className="spin" size={16} /> Sending...</> : <><Play size={15} /> Create reservation</>}</button></form>{error && <ErrorBox message={error} />}</section><section className="panel table-panel"><div className="panel-heading"><div><span className="section-kicker">TARGETS</span><h3>Table registry</h3></div><span className="recorded-label">API HAS NO LIST ROUTE</span></div><p className="panel-note">Provision a known target through the real <code>POST /tables</code> route. Availability is only known after a reservation response.</p><div className="table-grid">{['t1', 't2', 't3', 't4'].map((id, index) => <button className={`table-card ${form.table_id === id ? 'selected' : ''}`} key={id} onClick={() => update('table_id', id)}><span className="table-number">0{index + 1}</span><strong>{id.toUpperCase()}</strong><small>CAPACITY 4</small><span className="table-action" onClick={(event) => { event.stopPropagation(); provision(id) }}><Plus size={13} /> provision</span></button>)}</div>{tableMessage && <div className="inline-note"><Check size={14} /> {tableMessage}</div>}{result && <ReservationCard result={result} />}</section></div><section className="content-section attack-section"><div className="section-title"><div><span className="section-kicker">02 / CONCURRENCY ATTACK</span><h2>Put PostgreSQL under pressure</h2><p>All requests use one real idempotency key. The results below are from this browser session.</p></div><span className="recorded-label">PERSISTENT TEST DATA</span></div><div className="attack-console"><div className="attack-controls"><Field label="Requests" type="number" value={attack.count} onChange={(value) => setAttack((current) => ({ ...current, count: value }))} hint="2–25 per run" /><button className="primary-button" onClick={runAttack} disabled={attack.running}>{attack.running ? <><RefreshCw className="spin" size={16} /> Running...</> : <><Zap size={16} /> Run concurrency test</>}</button></div>{attack.result ? <div className="attack-result"><div className="attack-result-head"><div><span className="section-kicker">LIVE RESULT</span><h3>{attack.result.sent} requests completed</h3></div><StatusBadge status={attack.result.failed ? 'DEGRADED' : 'PASS'} /></div><div className="attack-metrics"><MetricCard label="Requests sent" value={attack.result.sent} detail="Real HTTP calls" icon={Activity} /><MetricCard label="Initial success" value={attack.result.success} detail="201 created" icon={Check} /><MetricCard label="Idempotent replay" value={attack.result.replay} detail="200 same row" icon={LockKeyhole} tone="blue" /><MetricCard label="Conflicts" value={attack.result.conflicts} detail="409 responses" icon={ShieldCheck} tone="amber" /></div><div className="attack-footnote"><Database size={15} /> The database invariant can be checked in the backend evidence; this UI has no delete route and intentionally labels test data as persistent.</div></div> : <div className="attack-empty"><div className="attack-flow"><span>{attack.count || 8} REQUESTS</span><ChevronRight /><span className="flow-core"><Database size={17} /> POSTGRESQL</span><ChevronRight /><strong>ONE WINNER</strong></div><p>Run the attack to replace this diagram with actual response counts.</p></div>}</div></section></>
}

function Field({ label, value, onChange, type = 'text', hint, wide = false }) { return <label className={`field ${wide ? 'wide' : ''}`}><span>{label}</span><input type={type} value={value} onChange={(event) => onChange(event.target.value)} required={label !== 'Requests'} /><small>{hint || ' '}</small></label> }
function ReservationCard({ result }) { return <div className="reservation-card"><div className="reservation-card-head"><div><span className="section-kicker">API RESPONSE</span><h3>Reservation accepted</h3></div><StatusBadge status={result.status?.toUpperCase() || 'ACTIVE'} /></div><div className="detail-grid"><Detail label="Reservation ID" value={result.reservation_id} mono /><Detail label="Table" value={result.table_id} /><Detail label="Start" value={result.start_time} mono /><Detail label="End" value={result.end_time} mono /><Detail label="Created" value={result.created_at} mono /><Detail label="Status" value={result.status} /></div></div> }
function Detail({ label, value, mono }) { return <div className="detail-item"><small>{label}</small><strong className={mono ? 'mono' : ''}>{value}</strong></div> }
function ErrorBox({ message }) { return <div className="error-box"><AlertTriangle size={16} /><span>{message}</span></div> }
function formatApiError(error) { if (error.name === 'AbortError') return 'The API request timed out. Check that FastAPI is running.'; if (!error.status) return 'Backend unavailable. Start FastAPI on the configured API URL.'; if (error.code === 'OVERLAP_CONFLICT') return 'Reservation rejected: this table is already reserved for that time window.'; if (error.code === 'IDEMPOTENCY_PAYLOAD_MISMATCH') return 'This idempotency key is already bound to a different payload.'; return error.message }

function AgentPipeline() { return <><PageHeading eyebrow="AGENT PIPELINE / RECORDED" title="Four roles. One proof." detail="Agent status is sourced from recorded factory evidence, not a live orchestration feed." /><div className="agent-grid">{[['ARCHITECT', 'Planning and invariants', 'evidence/plan.md', BookOpen], ['BUILDER', 'Implementation and tests', '46 passed', HardDrive], ['BREAKER', 'Adversarial verification', '25 + repeated concurrency', Zap], ['VERIFIER', 'Independent final validation', '46 passed · 1 warning', ShieldCheck]].map(([name, role, evidence, Icon]) => <div className="agent-card" key={name}><div className="agent-card-top"><div className="agent-icon"><Icon size={20} /></div><StatusBadge status="PASS" /></div><span className="section-kicker">RECORDED AGENT</span><h2>{name}</h2><p>{role}</p><div className="agent-evidence"><FileCheck2 size={14} /> {evidence}</div></div>)}</div><div className="panel agent-note"><Sparkles size={18} /><div><strong>Live BAND activity is not available in this UI.</strong><p>These cards deliberately identify recorded evidence instead of implying an active agent session.</p></div></div></> }

function EvidenceCenter() { const [selected, setSelected] = useState(evidenceItems[0]); const [query, setQuery] = useState(''); const filtered = useMemo(() => evidenceItems.filter((item) => `${item.name} ${item.summary}`.toLowerCase().includes(query.toLowerCase())), [query]); const copy = () => navigator.clipboard?.writeText(selected.content); return <><PageHeading eyebrow="EVIDENCE CENTER / BUILD-TIME MANIFEST" title="Proof, in full view" detail="These documents are imported from the repository's real evidence directory at build time." action={<span className="recorded-label"><FileCheck2 size={14} /> SOURCE: /evidence</span>} /><div className="evidence-layout"><section className="panel evidence-list"><div className="search-box"><Activity size={15} /><input placeholder="Filter evidence" value={query} onChange={(event) => setQuery(event.target.value)} /></div>{filtered.map((item) => <button className={`evidence-list-item ${selected.name === item.name ? 'selected' : ''}`} key={item.name} onClick={() => setSelected(item)}><div><strong>{item.name}</strong><small>{item.type} · {item.summary}</small></div><StatusBadge status={item.status} /></button>)}</section><section className="panel evidence-viewer"><div className="viewer-head"><div><span className="section-kicker">{selected.type}</span><h3>{selected.name}</h3></div><button className="icon-button" title="Copy evidence" onClick={copy}><Copy size={16} /></button></div><pre>{selected.content}</pre></section></div></> }

function Health({ backendStatus }) { return <><PageHeading eyebrow="SYSTEM HEALTH / OBSERVED" title="Know what is online" detail="Only the API status is actively measured. Database status is not exposed by the current backend and is intentionally unknown." action={<button className="quiet-button" onClick={() => window.location.reload()}><RefreshCw size={15} /> Recheck</button>} /><div className="health-grid"><HealthCard label="Frontend" status="ONLINE" detail="Vite application rendered in this browser." icon={Gauge} /><HealthCard label="Backend API" status={backendStatus === 'ONLINE' ? 'ONLINE' : backendStatus} detail="Measured with a real HTTP probe against FastAPI." icon={Server} /><HealthCard label="Database" status="UNKNOWN" detail="No public health route; PostgreSQL is not guessed from the UI." icon={Database} /></div><div className="panel health-panel"><div className="panel-heading"><div><span className="section-kicker">CONNECTION DETAILS</span><h3>Runtime configuration</h3></div></div><div className="detail-grid"><Detail label="API base URL" value={apiBaseUrl} mono /><Detail label="Probe route" value="GET /docs" mono /><Detail label="Interpretation" value="HTTP < 500 = API reachable" /></div></div></> }
function HealthCard({ label, status, detail, icon: Icon }) { return <div className="health-card"><div className="health-icon"><Icon size={20} /></div><div><span>{label}</span><h2>{status}</h2><p>{detail}</p></div><span className={`health-dot ${status.toLowerCase()}`} /></div> }

function About() { return <><PageHeading eyebrow="ABOUT / THE METHOD" title="Software engineering, reimagined as a factory." detail="A system for turning objectives into software that has survived its own attack." /><section className="about-hero"><span className="section-kicker">THE CORE PRINCIPLE</span><h2>AI agents do not simply generate code.<br /><em>They produce software, challenge it, repair it, and prove it.</em></h2></section><div className="method-grid">{[['01', 'Human', 'Defines the objective and remains the final authority.'], ['02', 'Architect', 'Maps requirements, invariants, risks, and acceptance tests.'], ['03', 'Builder', 'Implements the smallest working system and verifies it.'], ['04', 'Breaker', 'Attacks assumptions with adversarial, reproducible tests.'], ['05', 'Repair', 'Fixes root causes only when a genuine defect appears.'], ['06', 'Verifier', 'Independently checks the result before human acceptance.']].map(([number, title, copy]) => <div className="method-step" key={number}><span>{number}</span><h3>{title}</h3><p>{copy}</p></div>)}</div></> }

export default App