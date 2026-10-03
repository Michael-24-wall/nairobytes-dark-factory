import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { NavLink, Route, Routes, useLocation, useNavigate, useParams } from 'react-router-dom'
import {
  Activity, AlertTriangle, ArrowDown, ArrowUpRight, Beaker, BookOpen, Boxes, Check,
  ChevronRight, CircleHelp, Clock3, Copy, Database, FileCheck2, Gauge, GitBranch,
  GitPullRequest, HardDrive, Layers3, LayoutDashboard, Link2, LockKeyhole, Menu, Play,
  Plus, RefreshCw, Server, Settings2, ShieldCheck, ShoppingCart, Sparkles, TerminalSquare,
  Unlink, WalletCards,
  Github,
  Upload,
  Zap,
} from 'lucide-react'
import { apiBaseUrl } from './api/client'
import { approveFactoryRun, getFactoryEvents, getFactoryMetrics, getFactoryRun, getFactoryRuntime, getFactoryTasks, getFactoryTimeline, startFactoryRun } from './api/factory'
import {
  connectProjectGitHub, createGitHubRepository, createProjectPullRequest, disconnectProjectGitHub,
  getGitHubInstallations, getGitHubRepositories, getGitHubStatus, getProjectGitHub,
  getProjectPullRequest, publishProjectRun,
} from './api/github'
import { createProject, getProject, listProjects, updateProjectDesign, uploadProjectAsset } from './api/projects'
import { createReservation, createReservationWithStatus, createTable, getAvailability, getReservation } from './api/reservations'
import { createAccount, createTransfer, getAccount, getAccountEntries, getTrialBalance } from './api/payments'
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
  ['/', 'Overview', LayoutDashboard],
  ['/dashboard', 'Dashboard', Gauge],
  ['/projects', 'Projects', Boxes],
  ['/reservations', 'Reservations', Layers3],
  ['/payments', 'Payments', WalletCards],
  ['/factory', 'Factory Run', GitBranch],
  ['/idempotency', 'Idempotency Lab', LockKeyhole],
  ['/timezone', 'Timezone Lab', Clock3],
  ['/attacks', 'Attack Lab', Zap],
  ['/agents', 'Agent Pipeline', Sparkles],
  ['/evidence', 'Evidence Center', FileCheck2],
  ['/health', 'System Health', Activity],
  ['/settings', 'Settings', Settings2],
  ['/settings/github', 'GitHub Integration', Github],
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
  const [mobileNav, setMobileNav] = useState(false)
  const backendQuery = useQuery({ queryKey: ['backend-health'], queryFn: async () => { const response = await fetch(`${apiBaseUrl}/docs`, { signal: AbortSignal.timeout(4000) }); if (!response.ok) throw new Error(`API returned ${response.status}`); return 'ONLINE' }, refetchInterval: 30000, retry: false })
  const backendStatus = backendQuery.isPending ? 'CHECKING' : backendQuery.data || 'OFFLINE'

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
        <div className="page-wrap"><Routes><Route path="/" element={<Landing />} /><Route path="/dashboard" element={<Dashboard backendStatus={backendStatus} />} /><Route path="/projects" element={<Projects />} /><Route path="/projects/new" element={<ProjectCreation />} /><Route path="/projects/:projectId" element={<ProjectDetailLive />} /><Route path="/projects/:projectId/github" element={<GitHubProject />} /><Route path="/reservations" element={<ReservationLab />} /><Route path="/payments" element={<PaymentLab />} /><Route path="/factory" element={<FactoryRun />} /><Route path="/idempotency" element={<IdempotencyLab />} /><Route path="/timezone" element={<TimezoneLab />} /><Route path="/attacks" element={<AttackLab />} /><Route path="/agents" element={<AgentPipeline />} /><Route path="/evidence" element={<EvidenceCenter />} /><Route path="/health" element={<Health backendStatus={backendStatus} />} /><Route path="/settings" element={<Settings />} /><Route path="/settings/github" element={<GitHubSettings />} /><Route path="/about" element={<About />} /><Route path="*" element={<Landing />} /></Routes></div>
      </main>
    </div>
  )
}

function PageCrumb() {
  const location = useLocation()
  const label = location.pathname.endsWith('/github') ? 'GitHub Integration' : navItems.find(([path]) => path === location.pathname)?.[1]
  return <strong>{(label || 'Dashboard').toUpperCase()}</strong>
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

function FactoryProofBadges() {
  const { data, isError } = useQuery({ queryKey: ['factory-metrics'], queryFn: getFactoryMetrics, refetchInterval: 5000 })
  if (isError) return <span className="landing-proof-item"><AlertTriangle size={13} /> Metrics unavailable</span>
  if (!data) return <span className="landing-proof-item"><RefreshCw className="spin" size={13} /> Reading live metrics</span>
  const { totals, runtime_available: online } = data
  return <><span className="landing-proof-item"><Check size={13} /> {totals.tasks} agent tasks recorded</span><span className="landing-proof-item"><ShieldCheck size={13} /> {totals.approved} human approvals</span><span className="landing-proof-item">{online ? <Check size={13} /> : <AlertTriangle size={13} />} Agents {online ? 'online' : 'offline'}</span></>
}

function Landing() {
  return <div className="landing-page"><section className="landing-hero"><div className="landing-copy"><span className="eyebrow">AI SOFTWARE ENGINEERING INFRASTRUCTURE</span><h1>Build software.<br /><em>Break it.</em><br />Verify it.<br /><strong>Ship with evidence.</strong></h1><p>Nairobytes Dark Factory coordinates specialized engineering agents to design, build, attack, repair, and independently verify software.</p><div className="landing-actions"><NavLink to="/factory" className="primary-button">Open Factory <ArrowUpRight size={16} /></NavLink><NavLink to="/evidence" className="outline-link">View verification <FileCheck2 size={15} /></NavLink></div><div className="landing-proof"><FactoryProofBadges /></div></div><div className="landing-visual"><div className="visual-grid" /><div className="visual-core"><div className="core-pulse" /><ShieldCheck size={30} /><span>PROOF<br /><b>READY</b></span></div><div className="visual-label label-one">REQUIREMENT <ArrowDown size={14} /></div><div className="visual-label label-two">EVIDENCE <Check size={14} /></div><div className="visual-orbit orbit-a" /><div className="visual-orbit orbit-b" /></div></section><section className="landing-pipeline"><div className="section-title"><div><span className="section-kicker">THE FACTORY MODEL</span><h2>Specialists create the proof chain.</h2></div><span className="recorded-label">RECORDED EXAMPLE / TABLEKEEPER</span></div><Pipeline /></section><section className="landing-bottom"><div><span className="section-kicker">CURRENT DEMONSTRATION</span><h2>Restaurant reservations, engineered for correctness.</h2><p>The reservation system is the verified tablekeeper example. The factory itself is general-purpose infrastructure for software where concurrency, reliability, and evidence matter.</p></div><NavLink to="/projects" className="text-link">Explore project tracks <ArrowUpRight size={15} /></NavLink></section></div>
}

function Projects() {
  const projectsQuery = useQuery({ queryKey: ['projects'], queryFn: listProjects })
  const liveProjects = projectsQuery.data || []
  const projects = [
    ['Restaurant Reservations', 'VERIFIED', 'The current tablekeeper demonstration: overlap protection, idempotency, timezone correctness, and adversarial evidence.', Layers3, 'green', '/reservations'],
    ['Payment / Wallet Systems', 'VERIFIED', 'Real double-entry wallet: ledger integrity, idempotent transfers, a no-overdraft invariant, and concurrency-safe settlement.', WalletCards, 'green', '/payments'],
    ['Banking Transactions', 'CONCEPT', 'A future track for atomic transfers, concurrency boundaries, and auditable state transitions.', Database, 'blue'],
    ['Inventory Systems', 'CONCEPT', 'A future track for stock reservations, race conditions, fulfillment, and reconciliation.', Boxes, 'blue'],
    ['Healthcare Scheduling', 'CONCEPT', 'A future track for time windows, resource contention, and safe scheduling rules.', Clock3, 'blue'],
    ['Enterprise Workflows', 'CONCEPT', 'A future track for approvals, orchestration, permissions, and durable evidence.', GitBranch, 'blue'],
  ]
  return <><PageHeading eyebrow="PROJECTS / FACTORY TRACKS" title="One factory. Many systems." detail="The platform is general-purpose. The reservation system is the current verified example, not the boundary of the product." action={<NavLink to="/projects/new" className="primary-button"><Plus size={15} /> Create project</NavLink>} /><div className="project-banner"><div><span className="section-kicker">VERIFIED NOW</span><h2>Tablekeeper reservation system</h2><p>Overlap protection, idempotency and timezone correctness, enforced in PostgreSQL and covered by the test suite. Factory activity below is read live from the backend.</p></div><StatusBadge status="VERIFIED" /><NavLink to="/reservations" className="outline-link">Open demonstration <ArrowUpRight size={15} /></NavLink></div>{liveProjects.length > 0 && <section className="live-projects"><div className="section-title"><div><span className="section-kicker">LIVE PROJECTS</span><h2>Created workspaces</h2></div></div><div className="project-grid">{liveProjects.map((project) => <NavLink to={`/projects/${project.id}`} className="project-card live-project-card" key={project.id}><div className="project-icon"><Boxes size={20} /></div><div className="project-card-head"><span className="section-kicker">REAL RECORD</span><StatusBadge status={project.status.toUpperCase()} /></div><h3>{project.name}</h3><p>{project.description || 'No description provided.'}</p><span className="text-link">Open project <ArrowUpRight size={14} /></span></NavLink>)}</div></section>}{projectsQuery.isError && <ErrorBox message="Projects could not be loaded from the backend." />}<div className="project-grid">{projects.map(([name, status, description, Icon, tone, to]) => <article className={`project-card ${tone}`} key={name}><div className="project-icon"><Icon size={20} /></div><div className="project-card-head"><span className="section-kicker">{status === 'VERIFIED' ? 'LIVE EXAMPLE' : 'FUTURE TRACK'}</span><StatusBadge status={status} /></div><h3>{name}</h3><p>{description}</p>{status === 'VERIFIED' && <NavLink to={to || '/dashboard'} className="text-link">Open demonstration <ArrowUpRight size={14} /></NavLink>}</article>)}</div></>
}

const projectTypes = ['Website', 'Web Application', 'SaaS Application', 'Dashboard', 'API', 'E-commerce', 'Booking System', 'Reservation System', 'Customer Portal', 'Admin System', 'Custom Software']
const designDefaults = { primary_color: '#0B5ED7', secondary_color: '#FFFFFF', accent_color: '#DC2626', background_color: '#FFFFFF', text_color: '#111827', button_color: '#0B5ED7', warning_color: '#F59E0B', visual_style: 'Professional', theme: 'Light', custom_instructions: '' }

function ProjectCreation() {
  const navigate = useNavigate()
  const [step, setStep] = useState(1)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [project, setProject] = useState({ name: '', description: '', project_type: 'Website', target_users: '', business_domain: '', functional_requirements: '', nonfunctional_requirements: '', technology_preferences: 'React, Vite, Tailwind CSS', database_requirements: '', authentication_requirement: 'No authentication' })
  const [design, setDesign] = useState(designDefaults)
  const [asset, setAsset] = useState({ file: null, alt_text: '', asset_type: 'Logo', section: 'Header' })
  const updateProject = (key, value) => setProject((current) => ({ ...current, [key]: value }))
  const updateDesign = (key, value) => setDesign((current) => ({ ...current, [key]: value }))
  const submit = async (event) => { event.preventDefault(); setBusy(true); setError(''); try { const created = await createProject(project); await updateProjectDesign(created.id, design); if (asset.file) await uploadProjectAsset(created.id, asset.file, asset); navigate(`/projects/${created.id}`) } catch (requestError) { setError(formatApiError(requestError)) } finally { setBusy(false) } }
  return <><PageHeading eyebrow="PROJECTS / NEW WORKSPACE" title="Describe what you want to build." detail="This creates a real project record, design system, isolated workspace, and optional first asset. Agent execution is a later, explicit stage." action={<StatusBadge status="DRAFT" />} /><div className="wizard-shell"><div className="wizard-steps">{[['01', 'Requirements'], ['02', 'Design & Branding'], ['03', 'Assets & Review']].map(([number, label], index) => <button className={step === index + 1 ? 'active' : step > index + 1 ? 'complete' : ''} key={number} onClick={() => step > index + 1 && setStep(index + 1)}><span>{step > index + 1 ? <Check size={14} /> : number}</span>{label}</button>)}</div><form onSubmit={submit} className="wizard-form panel">{step === 1 && <div className="wizard-content"><WizardTitle number="01" title="Project requirements" detail="These inputs become the Architect's source of truth." /><div className="form-grid"><Field label="Project name" value={project.name} onChange={(value) => updateProject('name', value)} hint="Required" /><label className="field"><span>Project type</span><select value={project.project_type} onChange={(event) => updateProject('project_type', event.target.value)}>{projectTypes.map((type) => <option key={type}>{type}</option>)}</select><small>Extensible factory workload</small></label><TextArea label="Description" value={project.description} onChange={(value) => updateProject('description', value)} wide hint="What should this software achieve?" /><TextArea label="Functional requirements" value={project.functional_requirements} onChange={(value) => updateProject('functional_requirements', value)} wide hint="One requirement per line" /><TextArea label="Non-functional requirements" value={project.nonfunctional_requirements} onChange={(value) => updateProject('nonfunctional_requirements', value)} wide hint="Performance, accessibility, SEO, reliability..." /><Field label="Target users" value={project.target_users} onChange={(value) => updateProject('target_users', value)} /><Field label="Business / domain" value={project.business_domain} onChange={(value) => updateProject('business_domain', value)} /><Field label="Technology preferences" value={project.technology_preferences} onChange={(value) => updateProject('technology_preferences', value)} /><Field label="Database requirements" value={project.database_requirements} onChange={(value) => updateProject('database_requirements', value)} /></div></div>}{step === 2 && <div className="wizard-content"><WizardTitle number="02" title="Design & branding" detail="These tokens belong to this project and are stored for the future Builder." /><div className="design-preview" style={{ '--preview-primary': design.primary_color, '--preview-secondary': design.secondary_color, '--preview-accent': design.accent_color }}><span>LIVE PREVIEW</span><div><strong>{project.name || 'Your project'}</strong><small>Project design tokens preview</small></div><button type="button">Primary action</button></div><div className="color-grid">{[['primary_color', 'Primary color'], ['secondary_color', 'Secondary color'], ['accent_color', 'Accent color'], ['background_color', 'Background color'], ['text_color', 'Text color'], ['button_color', 'Button color'], ['warning_color', 'Warning color']].map(([key, label]) => <label className="color-field" key={key}><span>{label}</span><div><input type="color" value={design[key]} onChange={(event) => updateDesign(key, event.target.value)} /><input value={design[key]} pattern="^#[0-9A-Fa-f]{6}$" onChange={(event) => updateDesign(key, event.target.value)} /></div></label>)}</div><div className="form-grid design-selects"><label className="field"><span>Visual style</span><select value={design.visual_style} onChange={(event) => updateDesign('visual_style', event.target.value)}>{['Modern', 'Minimal', 'Corporate', 'Luxury', 'Creative', 'Technology', 'E-commerce', 'Professional', 'Editorial', 'Custom'].map((style) => <option key={style}>{style}</option>)}</select><small>Passed to the future Architect</small></label><label className="field"><span>Theme</span><select value={design.theme} onChange={(event) => updateDesign('theme', event.target.value)}>{['Light', 'Dark', 'System'].map((theme) => <option key={theme}>{theme}</option>)}</select><small>Generated app preference</small></label><TextArea label="Custom design instructions" value={design.custom_instructions} onChange={(value) => updateDesign('custom_instructions', value)} wide hint="Example: spacious, premium, suitable for a technology company." /></div></div>}{step === 3 && <div className="wizard-content"><WizardTitle number="03" title="Assets & review" detail="Upload one real asset now, assign its intended use, and create the workspace." /><div className="asset-drop"><UploadCloudIcon /><label><strong>{asset.file ? asset.file.name : 'Choose a logo or hero image'}</strong><small>PNG, JPEG, WebP, GIF, SVG, ICO or PDF · max 10 MB</small><input type="file" accept="image/*,.pdf" onChange={(event) => setAsset((current) => ({ ...current, file: event.target.files?.[0] || null }))} /></label></div>{asset.file && <div className="form-grid"><Field label="Alt text" value={asset.alt_text} onChange={(value) => setAsset((current) => ({ ...current, alt_text: value }))} /><label className="field"><span>Asset type</span><select value={asset.asset_type} onChange={(event) => setAsset((current) => ({ ...current, asset_type: event.target.value }))}>{['Logo', 'Favicon', 'Hero image', 'Product image', 'Team photo', 'Background image', 'Gallery image', 'Document', 'Other'].map((type) => <option key={type}>{type}</option>)}</select><small>Architect / Builder assignment</small></label><Field label="Section" value={asset.section} onChange={(value) => setAsset((current) => ({ ...current, section: value }))} /></div>}<div className="review-grid"><Detail label="Project" value={project.name || 'Not entered'} /><Detail label="Type" value={project.project_type} /><Detail label="Style" value={`${design.visual_style} / ${design.theme}`} /><Detail label="Workspace" value="Created automatically" /></div></div>}{error && <ErrorBox message={error} />}<div className="wizard-actions">{step > 1 && <button type="button" className="quiet-button" onClick={() => setStep(step - 1)}>Back</button>}{step < 3 ? <button type="button" className="primary-button" onClick={() => setStep(step + 1)} disabled={step === 1 && !project.name}>Continue <ChevronRight size={15} /></button> : <button className="primary-button" disabled={busy}>{busy ? <><RefreshCw className="spin" size={15} /> Creating workspace...</> : <><Plus size={15} /> Create project</>}</button>}</div></form></div></>
}

function WizardTitle({ number, title, detail }) { return <div className="wizard-title"><span>{number}</span><div><h2>{title}</h2><p>{detail}</p></div></div> }
function TextArea({ label, value, onChange, hint, wide = false }) { return <label className={`field ${wide ? 'wide' : ''}`}><span>{label}</span><textarea aria-label={label} value={value} onChange={(event) => onChange(event.target.value)} /><small>{hint || ' '}</small></label> }
function UploadCloudIcon() { return <div className="upload-icon"><Plus size={21} /></div> }

function ProjectDetail() {
  const { projectId } = useParams()
  const query = useQuery({ queryKey: ['project', projectId], queryFn: () => getProject(projectId) })
  if (query.isPending) return <LoadingState label="Loading project workspace..." />
  if (query.isError) return <ErrorBox message="Project could not be loaded from the backend." />
  const project = query.data
  return <><PageHeading eyebrow={`PROJECT / ${project.slug}`} title={project.name} detail={project.description || 'No description provided.'} action={<StatusBadge status={project.status.toUpperCase()} />} /><div className="project-detail-grid"><section className="panel project-detail-main"><div className="panel-heading"><div><span className="section-kicker">REQUIREMENTS</span><h3>Source of truth</h3></div><span className="recorded-label">REAL RECORD</span></div><div className="detail-grid detail-grid-wide"><Detail label="Type" value={project.project_type} /><Detail label="Domain" value={project.business_domain || 'Not specified'} /><Detail label="Target users" value={project.target_users || 'Not specified'} /><Detail label="Authentication" value={project.authentication_requirement} /><Detail label="Functional requirements" value={project.functional_requirements || 'Not specified'} /><Detail label="Non-functional requirements" value={project.nonfunctional_requirements || 'Not specified'} /><Detail label="Technology preferences" value={project.technology_preferences || 'Not specified'} /><Detail label="Database requirements" value={project.database_requirements || 'Not specified'} /></div></section><section className="panel project-design-card"><div className="panel-heading"><div><span className="section-kicker">DESIGN TOKENS</span><h3>{project.design?.visual_style} / {project.design?.theme}</h3></div><Sparkles size={18} /></div><div className="swatch-row">{['primary_color', 'secondary_color', 'accent_color', 'background_color', 'text_color', 'button_color'].map((key) => <div key={key}><span style={{ background: project.design?.[key] }} /><small>{key.replace('_color', '')}</small></div>)}</div><p>{project.design?.custom_instructions || 'No custom design instructions.'}</p></section></div><section className="panel assets-panel"><div className="panel-heading"><div><span className="section-kicker">ASSET REGISTER</span><h3>Assigned project assets</h3></div><span className="recorded-label">{project.assets.length} REAL ASSET{project.assets.length === 1 ? '' : 'S'}</span></div>{project.assets.length ? <div className="asset-list">{project.assets.map((asset) => <div className="asset-row" key={asset.id}><div className="asset-thumb">{asset.mime_type.startsWith('image/') ? <img src={`${apiBaseUrl}${asset.url}`} alt={asset.alt_text || asset.original_filename} /> : <FileCheck2 size={18} />}</div><div><strong>{asset.original_filename}</strong><small>{asset.asset_type} · {asset.section || 'Unassigned'} · {Math.ceil(asset.size / 1024)} KB</small></div><a href={`${apiBaseUrl}${asset.url}`} target="_blank" rel="noreferrer" className="text-link">Open <ArrowUpRight size={14} /></a></div>)}</div> : <EmptyState title="No assets uploaded" detail="Return to project creation to add a real logo, hero image, or document." action={<NavLink to="/projects/new" className="outline-link">Create another project</NavLink>} />}</section><section className="project-detail-grid"><div className="panel workspace-card"><div className="panel-heading"><div><span className="section-kicker">WORKSPACE</span><h3>Isolated execution boundary</h3></div><StatusBadge status={project.workspace?.status?.toUpperCase() || 'UNKNOWN'} /></div><Detail label="Workspace path" value={project.workspace?.path || 'Unavailable'} mono /><p>Factory execution is not started for this project. Architect, Builder, Tester, Breaker, Repair, Verifier, GitHub, and Deployment remain explicit next stages.</p></div><div className="panel"><div className="panel-heading"><div><span className="section-kicker">INTEGRATIONS</span><h3>GitHub App</h3></div><Server size={18} /></div><div className="boundary"><Check size={14} /><span>Link a repository, push verified runs to a factory branch, and open a real pull request.</span></div><div className="action-row"><NavLink className="outline-link" to={`/projects/${project.id}/github`}><Github size={15} /> Open GitHub publishing <ChevronRight size={14} /></NavLink></div><div className="boundary"><CircleHelp size={14} /><span>Deployment, auth, and storage remain outside this system.</span></div></div></section></>
}

const AGENT_STAGES = [
  ['architect', 'Architect', 'Maps requirements, invariants, risks, acceptance tasks'],
  ['builder', 'Builder', 'Implements the smallest working system'],
  ['breaker', 'Breaker', 'Attacks assumptions with reproducible tests'],
  ['repair', 'Repair', 'Fixes root causes only on a proven defect'],
  ['verifier', 'Verifier', 'Independently verifies before human acceptance'],
]

function AgentHandoffChain({ timeline, runtime }) {
  const tasks = timeline?.tasks || []
  const mode = timeline?.execution_mode
  const hasRun = Boolean(timeline?.run)
  const handoffs = timeline?.handoffs || []
  const events = timeline?.events || []
  return <section className="panel agent-chain-panel"><div className="panel-heading"><div><span className="section-kicker">AGENT HAND-OFF CHAIN</span><h3>{!hasRun ? 'No run recorded yet' : mode === 'live' ? 'Live agents' : 'Templated pipeline'}</h3></div>{hasRun && <StatusBadge status={mode === 'live' ? 'LIVE AGENTS' : 'TEMPLATED'} />}</div>{!hasRun && <div className="inline-note"><AlertTriangle size={14} /> No factory run has been recorded yet, so every role is PENDING. Start one from a project page (/projects &rarr; Run factory) to see the real hand-off chain.</div>}{hasRun && mode !== 'live' && <div className="inline-note"><AlertTriangle size={14} /> No agent runtime was reachable for this run, so these stages ran from templates. Nothing here was produced by a model.</div>}{runtime && <div className="run-state-grid"><Detail label="Runtime" value={runtime.available ? `${runtime.provider_id}/${runtime.model_id}` : 'unreachable'} mono /><Detail label="Agent budget" value={`${runtime.timeout_seconds}s per stage`} /><Detail label="Repair rounds" value={String(runtime.max_repair_rounds)} /></div>}<div className="agent-chain">{AGENT_STAGES.map(([role, label, blurb]) => { const mine = tasks.filter((task) => task.agent_role === role); const state = mine.length === 0 ? 'pending' : mine.every((task) => task.status === 'passed') ? 'passed' : mine.some((task) => task.status === 'running') ? 'running' : 'failed'; const verdict = mine.map((task) => task.verdict).filter(Boolean).pop(); return <div className={`agent-chain-row ${state}`} key={role}><div className="agent-chain-marker"><span /></div><div className="agent-chain-body"><div className="agent-chain-head"><strong>{label}</strong><StatusBadge status={verdict ? `verdict ${verdict}` : state.toUpperCase()} /></div><p>{blurb}</p>{mine.length > 0 && <ul>{mine.map((task) => <li key={task.id}><span className="agent-chain-seq">#{task.sequence}</span> {task.task_type}<StatusBadge status={task.status.toUpperCase()} />{task.handed_to && <small className="agent-handed-to">&#8594; handed off to {task.handed_to}</small>}{task.agent_session_id && <small className="agent-session">{task.agent_session_id}</small>}</li>)}</ul>}</div></div> })}</div>{handoffs.length > 0 && <div className="agent-handoff-record"><div className="handoff-record-head"><span className="section-kicker">LIVE FACTORY ACTIVITY</span><span className="recorded-label">REAL RECORDED HAND-OFFS</span></div><ol className="handoff-record">{handoffs.map((entry) => <li key={entry.id}><span className="handoff-from">{entry.from_role}</span><span className="handoff-arrow">&#8594;</span><span className="handoff-to">{entry.to_role || 'next'}</span><span className="handoff-copy">{entry.message}</span><small>{entry.stage} &middot; {entry.created_at}</small></li>)}</ol></div>}{events.length > 0 && <div className="factory-event-timeline"><div className="handoff-record-head"><span className="section-kicker">EVENT TIMELINE</span><span className="recorded-label">{events.length} PERSISTED EVENTS</span></div><ol>{events.map((event) => <li key={event.id}><time>{String(event.created_at).slice(11, 19)}</time><span className="event-type">{event.event_type}</span><span className="event-message">{event.message}</span></li>)}</ol></div>}{tasks.length > 0 && <div className="agent-handoff-outputs">{tasks.filter((task) => task.output).slice(-3).map((task) => <details key={task.id}><summary>{task.agent_role} handoff &rarr; next agent</summary><pre>{task.output}</pre></details>)}</div>}</section>
}

function ProjectDetailLive() {
  const { projectId } = useParams()
  const [runId, setRunId] = useState('')
  const [error, setError] = useState('')
  const runQuery = useQuery({ queryKey: ['factory-run', runId], queryFn: () => getFactoryRun(runId), enabled: Boolean(runId), refetchInterval: runId ? 1000 : false })
  const eventsQuery = useQuery({ queryKey: ['factory-events', runId], queryFn: () => getFactoryEvents(runId), enabled: Boolean(runId), refetchInterval: runId ? 1000 : false })
  const tasksQuery = useQuery({ queryKey: ['factory-tasks', runId], queryFn: () => getFactoryTasks(runId), enabled: Boolean(runId), refetchInterval: runId ? 1000 : false })
  const timelineQuery = useQuery({ queryKey: ['factory-timeline', runId], queryFn: () => getFactoryTimeline(runId), enabled: Boolean(runId), refetchInterval: runId ? 1500 : false })
  const runtimeQuery = useQuery({ queryKey: ['factory-runtime'], queryFn: getFactoryRuntime, refetchInterval: 10000 })
  const start = async () => { setError(''); try { const run = await startFactoryRun(projectId, `ui-factory-${projectId}`); setRunId(run.id) } catch (requestError) { setError(formatApiError(requestError)) } }
  const approve = async () => { try { await approveFactoryRun(runId, 'Approved from project workspace.'); runQuery.refetch() } catch (requestError) { setError(formatApiError(requestError)) } }
  return <><ProjectDetail /><section className="panel factory-control-panel"><div className="panel-heading"><div><span className="section-kicker">FACTORY EXECUTION / LIVE BACKEND STATE</span><h3>{runQuery.data ? runQuery.data.status.toUpperCase() : 'READY TO RUN'}</h3></div>{runQuery.data ? <StatusBadge status={runQuery.data.status.toUpperCase()} /> : <button className="primary-button" onClick={start}><Play size={15} /> Run factory</button>}</div>{error && <ErrorBox message={error} />}{runQuery.data ? <><div className="run-state-grid"><Detail label="Run ID" value={runQuery.data.id} mono /><Detail label="Current stage" value={runQuery.data.current_stage} /><Detail label="Error" value={runQuery.data.error || 'None'} /><Detail label="Started" value={runQuery.data.started_at || 'Queued'} mono /><Detail label="Execution mode" value={timelineQuery.data?.execution_mode || 'pending'} /></div><AgentHandoffChain timeline={timelineQuery.data} runtime={runtimeQuery.data} /><div className="factory-events">{(eventsQuery.data || []).map((event) => <div className="factory-event" key={event.id}><span /><div><strong>{event.message}</strong><small>{event.stage} · {event.created_at}</small></div></div>)}</div><div className="factory-tasks">{(tasksQuery.data || []).map((task) => <StatusBadge key={task.id} status={`${task.agent_role} ${task.status}`} />)}</div>{runQuery.data.status === 'awaiting_approval' && <button className="primary-button" onClick={approve}><ShieldCheck size={15} /> Approve verified run</button>}{runQuery.data.status === 'approved' && <div className="inline-note"><Check size={14} /> Human approval persisted. Deployment is NOT CONFIGURED.</div>}</> : <p className="factory-control-copy">This action creates a real queued run and starts local Architect, Builder, Tester, Breaker, Retest, Verifier, and Git stages. No progress is shown until the backend records it.</p>}</section></>
}

function LoadingState({ label }) { return <div className="loading-state"><RefreshCw className="spin" size={20} /><span>{label}</span></div> }
function EmptyState({ title, detail, action }) { return <div className="empty-state"><Boxes size={20} /><h3>{title}</h3><p>{detail}</p>{action}</div> }

function shiftWindow(startValue, endValue, hours) {
  const shift = (value) => {
    const match = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)(Z|[+-]\d{2}:?\d{2})?$/.exec(value || '')
    if (!match) return value
    const shifted = new Date(`${match[1]}Z`)
    if (Number.isNaN(shifted.getTime())) return value
    shifted.setUTCHours(shifted.getUTCHours() + hours)
    return `${shifted.toISOString().slice(0, 19)}${match[2] || 'Z'}`
  }
  return [shift(startValue), shift(endValue)]
}

const MAX_WINDOW_HOP = 48

async function resolveFreeWindow(tableId, startValue, endValue) {
  let windowStart = startValue
  let windowEnd = endValue
  for (let hop = 0; hop < MAX_WINDOW_HOP; hop += 1) {
    const probe = await getAvailability(tableId, windowStart, windowEnd)
    if (!probe.table_exists) return { start: windowStart, end: windowEnd, provisioned: false, hops: hop }
    if (probe.available) return { start: windowStart, end: windowEnd, provisioned: true, hops: hop }
    const shifted = shiftWindow(windowStart, windowEnd, 1)
    windowStart = shifted[0]
    windowEnd = shifted[1]
  }
  throw Object.assign(new Error(`No unbooked window found for ${tableId} within ${MAX_WINDOW_HOP} hours.`), { code: 'NO_FREE_WINDOW' })
}

async function runBurstOnFreeWindow(tableId, startValue, endValue, fire) {
  let target = await resolveFreeWindow(tableId, startValue, endValue)
  if (!target.provisioned) {
    await createTable({ table_id: tableId, capacity: 4 })
    target = await resolveFreeWindow(tableId, target.start, target.end)
  }
  const attempt = await fire(target.start, target.end)
  return { ...attempt, start: target.start, end: target.end }
}

function PaymentLab() {
  const [accounts, setAccounts] = useState([])
  const [accountForm, setAccountForm] = useState({ owner_name: 'Alice', currency: 'USD', opening_balance_minor: 1000 })
  const [transferForm, setTransferForm] = useState({ source_account: '', target_account: '', amount_minor: 250, currency: 'USD', idempotency_key: `pay-${Date.now()}` })
  const [transfer, setTransfer] = useState(null)
  const [transferStatus, setTransferStatus] = useState(null)
  const [entries, setEntries] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const trialQuery = useQuery({ queryKey: ['payments-trial'], queryFn: getTrialBalance, refetchInterval: 5000 })
  const balanceQuery = useQuery({ queryKey: ['payments-balances', accounts.map((account) => account.account_id).join(',')], queryFn: () => Promise.all(accounts.map((account) => getAccount(account.account_id))), enabled: accounts.length > 0, refetchInterval: 5000 })
  const balances = balanceQuery.data || accounts

  const addAccount = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const created = await createAccount(accountForm)
      setAccounts((current) => [...current, created])
      setTransferForm((current) => ({ ...current, source_account: current.source_account || created.account_id, target_account: current.target_account || created.account_id }))
    } catch (requestError) {
      setError(formatApiError(requestError))
    } finally {
      setBusy(false)
    }
  }

  const makeTransfer = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    setTransfer(null)
    setTransferStatus(null)
    setEntries(null)
    try {
      const result = await createTransfer(transferForm)
      setTransfer(result.data)
      setTransferStatus(result.status)
      setTransferForm((current) => ({ ...current, idempotency_key: `pay-${Date.now()}` }))
      balanceQuery.refetch()
      trialQuery.refetch()
    } catch (requestError) {
      setError(formatApiError(requestError))
    } finally {
      setBusy(false)
    }
  }

  const showEntries = async (accountId) => {
    setError(null)
    try {
      setEntries(await getAccountEntries(accountId))
    } catch (requestError) {
      setError(formatApiError(requestError))
    }
  }

  const accountName = (id) => balances.find((account) => account.account_id === id)?.owner_name || (id || '').slice(0, 8)

  const header = <PageHeading eyebrow="PAYMENT LAB / LIVE LEDGER" title="Move money, prove the books." detail="Real accounts, a real double-entry ledger, and real idempotent transfers against PostgreSQL. Overdrafts and unbalanced entries are rejected, never simulated." action={<span className="live-chip"><span className="pulse-dot" /> LIVE REQUESTS</span>} />

  const accountPanel = <section className="panel reservation-form-panel">
    <div className="panel-heading"><div><span className="section-kicker">01 / ACCOUNT</span><h3>Open an account</h3></div><WalletCards size={19} /></div>
    <form onSubmit={addAccount} className="form-grid">
      <Field label="Owner name" value={accountForm.owner_name} onChange={(value) => setAccountForm((current) => ({ ...current, owner_name: value }))} />
      <Field label="Currency" value={accountForm.currency} onChange={(value) => setAccountForm((current) => ({ ...current, currency: value }))} hint="3-letter ISO code" />
      <Field label="Opening balance (minor units)" type="number" value={accountForm.opening_balance_minor} onChange={(value) => setAccountForm((current) => ({ ...current, opening_balance_minor: Number(value) || 0 }))} wide hint="Cents: 1000 = 10.00" />
      <button className="primary-button wide" disabled={busy}>{busy ? <><RefreshCw className="spin" size={16} /> Working...</> : <><Plus size={15} /> Create account</>}</button>
    </form>
  </section>

  const trialPanel = <section className="panel">
    <div className="panel-heading"><div><span className="section-kicker">INVARIANT</span><h3>Ledger trial balance</h3></div><StatusBadge status={trialQuery.data?.balanced ? 'BALANCED' : 'CHECK'} /></div>
    <p className="panel-note">Double-entry guarantee: total debits must equal total credits. Read from <code>GET /payments/ledger/trial-balance</code>.</p>
    {trialQuery.data && <div className="detail-grid"><Detail label="Debits (minor)" value={String(trialQuery.data.debits_minor)} mono /><Detail label="Credits (minor)" value={String(trialQuery.data.credits_minor)} mono /><Detail label="Entries" value={String(trialQuery.data.entries)} /><Detail label="Accounts" value={String(trialQuery.data.accounts)} /><Detail label="Total balance" value={String(trialQuery.data.total_balance_minor)} mono /><Detail label="Balanced" value={trialQuery.data.balanced ? 'YES' : 'NO'} /></div>}
  </section>

  const transferPanel = <section className="panel reservation-form-panel">
    <div className="panel-heading"><div><span className="section-kicker">02 / TRANSFER</span><h3>Send a payment</h3></div><ArrowUpRight size={19} /></div>
    <form onSubmit={makeTransfer} className="form-grid">
      <label className="field"><span>Source account</span><select value={transferForm.source_account} onChange={(event) => setTransferForm((current) => ({ ...current, source_account: event.target.value }))} required>{balances.map((account) => <option key={account.account_id} value={account.account_id}>{account.owner_name} · {account.balance_minor}</option>)}</select><small>Debited</small></label>
      <label className="field"><span>Target account</span><select value={transferForm.target_account} onChange={(event) => setTransferForm((current) => ({ ...current, target_account: event.target.value }))} required>{balances.map((account) => <option key={account.account_id} value={account.account_id}>{account.owner_name} · {account.balance_minor}</option>)}</select><small>Credited</small></label>
      <Field label="Amount (minor units)" type="number" value={transferForm.amount_minor} onChange={(value) => setTransferForm((current) => ({ ...current, amount_minor: Number(value) || 0 }))} />
      <Field label="Currency" value={transferForm.currency} onChange={(value) => setTransferForm((current) => ({ ...current, currency: value }))} />
      <Field label="Idempotency key" value={transferForm.idempotency_key} onChange={(value) => setTransferForm((current) => ({ ...current, idempotency_key: value }))} wide hint="Reuse this key to see a real 200 replay with no second debit." />
      <button className="primary-button wide" disabled={busy || balances.length < 2}>{busy ? <><RefreshCw className="spin" size={16} /> Sending...</> : <><Play size={15} /> Send transfer</>}</button>
    </form>
    {error && <ErrorBox message={error} />}
  </section>

  const accountsPanel = <section className="panel">
    <div className="panel-heading"><div><span className="section-kicker">ACCOUNTS</span><h3>Balances (minor units)</h3></div><span className="recorded-label">READ FROM POSTGRES</span></div>
    {balances.length === 0 ? <p className="panel-note">No accounts yet. Create one on the left to start.</p> : <div className="table-grid">{balances.map((account) => <button className="table-card" key={account.account_id} onClick={() => showEntries(account.account_id)}><strong>{account.owner_name}</strong><span>{account.balance_minor} {account.currency}</span><small className="mono">{account.account_id.slice(0, 8)}</small></button>)}</div>}
  </section>

  const resultPanel = transfer && <section className="panel">
    <div className="panel-heading"><div><span className="section-kicker">API RESPONSE · HTTP {transferStatus}</span><h3>{transferStatus === 200 ? 'Idempotent replay (no new debit)' : 'Transfer settled'}</h3></div><StatusBadge status="SETTLED" /></div>
    <div className="detail-grid"><Detail label="Transfer ID" value={transfer.transfer_id} mono /><Detail label="From" value={accountName(transfer.source_account)} /><Detail label="To" value={accountName(transfer.target_account)} /><Detail label="Amount" value={`${transfer.amount_minor} ${transfer.currency}`} mono /><Detail label="Status" value={transfer.status} /><Detail label="Created" value={transfer.created_at} mono /></div>
  </section>

  const entriesPanel = entries && <section className="panel">
    <div className="panel-heading"><div><span className="section-kicker">LEDGER</span><h3>Entries for {accountName(entries.account_id)}</h3></div><span className="recorded-label">{entries.entries.length} ENTRIES</span></div>
    {entries.entries.length === 0 ? <p className="panel-note">No ledger entries for this account yet.</p> : <div className="factory-events">{entries.entries.map((entry) => <div className="factory-event" key={entry.entry_id}><span /><div><strong>{entry.direction.toUpperCase()} {entry.amount_minor}</strong><small className="mono">{entry.transfer_id}</small></div></div>)}</div>}
  </section>

  return <>{header}<div className="lab-grid">{accountPanel}{trialPanel}</div><div className="lab-grid">{transferPanel}{accountsPanel}</div>{resultPanel}{entriesPanel}</>
}

function AttackLab() {
  const [table, setTable] = useState('t1')
  const [start, setStart] = useState('2026-06-07T18:00:00+00:00')
  const [end, setEnd] = useState('2026-06-07T19:00:00+00:00')
  const [count, setCount] = useState(8)
  const [state, setState] = useState({ running: false, result: null, error: null })
  const [windowNote, setWindowNote] = useState('')
  const run = async () => {
    setState({ running: true, result: null, error: null })
    setWindowNote('')
    const targetTable = table
    const fire = async (windowStart, windowEnd) => {
      const key = `attack-ui-${crypto.randomUUID?.() || Date.now()}`
      const payload = { customer_name: 'Concurrency attack', table_id: targetTable, start_time: windowStart, end_time: windowEnd, idempotency_key: key }
      const total = Math.max(2, Math.min(100, Number(count) || 8))
      const responses = await Promise.all(Array.from({ length: total }, () => createReservationWithStatus(payload).then((response) => ({ status: response.status, body: response.data })).catch((error) => ({ status: error.status || 0, error }))))
      return { total, responses, missing: responses.filter((item) => item.status === 404).length }
    }
    let attempt
    try { attempt = await runBurstOnFreeWindow(targetTable, start, end, fire) } catch (error) { setState({ running: false, result: null, error: formatApiError(error) }); return }
    const { total, responses, missing } = attempt
    setState({ running: false, result: { total, success: responses.filter((item) => item.status === 201).length, replay: responses.filter((item) => item.status === 200).length, rejected: responses.filter((item) => item.status === 409).length, missing, failed: missing + responses.filter((item) => item.status === 0 || item.status >= 500).length }, error: null })
    const [nextStart, nextEnd] = shiftWindow(attempt.start, attempt.end, 1)
    setStart(nextStart)
    setEnd(nextEnd)
    setWindowNote(`Availability confirmed for ${attempt.start}, so the burst hit an unbooked slot. Next run starts at ${nextStart}.`)
  }
  const provision = async () => { try { await createTable({ table_id: table, capacity: 4 }); setState((current) => ({ ...current, error: `${table} provisioned. Run the attack when ready.` })) } catch (error) { setState((current) => ({ ...current, error: error.code === 'TABLE_EXISTS' ? `${table} already exists. Ready to attack.` : formatApiError(error) })) } }
  return <><PageHeading eyebrow="ATTACK LAB / LIVE CONCURRENCY" title="Try to break the booking invariant." detail="This sends real simultaneous HTTP requests to PostgreSQL-backed FastAPI. Results are never simulated." action={<span className="live-chip"><span className="pulse-dot" /> LIVE ATTACK</span>} /><div className="attack-brief"><div className="attack-brief-icon"><Zap size={22} /></div><div><span className="section-kicker">THE ATTACK</span><h2>Many simultaneous requests. One winner. No double booking.</h2><p>Identical idempotency keys demonstrate replay behavior. Availability is confirmed through <code>GET /tables/&#123;id&#125;/availability</code> before every burst, so repeat attacks always target an unbooked slot.</p></div></div><section className="panel attack-config"><div className="panel-heading"><div><span className="section-kicker">ATTACK CONFIGURATION</span><h3>Target the real reservation endpoint</h3></div><button className="outline-link" onClick={provision}><Plus size={15} /> Provision table</button></div><div className="attack-form"><Field label="Target table" value={table} onChange={setTable} /><Field label="Requests" type="number" value={count} onChange={setCount} hint="2–100 simultaneous requests" /><Field label="Start time" value={start} onChange={setStart} hint="ISO 8601 with offset" /><Field label="End time" value={end} onChange={setEnd} hint="ISO 8601 with offset" /><button className="primary-button wide" onClick={run} disabled={state.running}>{state.running ? <><RefreshCw className="spin" size={16} /> Executing attack...</> : <><Zap size={16} /> Run concurrency attack</>}</button></div>{state.error && <div className="inline-note"><AlertTriangle size={14} /> {state.error}</div>}{windowNote && <div className="inline-note"><Check size={14} /> {windowNote}</div>}</section>{state.result ? <section className="attack-result-large"><div className="attack-result-head"><div><span className="section-kicker">ACTUAL RESPONSE COUNTS</span><h2>{state.result.total} requests completed</h2></div><StatusBadge status={state.result.failed ? 'FAILED' : 'PASS'} /></div><div className="attack-stat-grid"><AttackStat label="Successful reservations" value={state.result.success} tone="success" /><AttackStat label="Idempotent replay" value={state.result.replay} tone="blue" /><AttackStat label="Rejected conflicts" value={state.result.rejected} tone="danger" /><AttackStat label="Missing table" value={state.result.missing} tone={state.result.missing ? 'danger' : 'neutral'} /><AttackStat label="Failed requests" value={state.result.failed} tone={state.result.failed ? 'danger' : 'neutral'} /></div><div className="invariant-result"><ShieldCheck size={19} /><div><strong>Database overlap invariant</strong><span>Use the recorded Breaker evidence to inspect the post-attack `overlapping_pair_count=0` result. This endpoint has no database inspection route.</span></div><StatusBadge status={state.result.failed ? 'UNKNOWN' : 'RECORDED PASS'} /></div></section> : <section className="attack-visual-empty"><div className="attack-flow-large"><span>{count || 8} REQUESTS</span><ArrowDown /><div><Database size={25} /><strong>POSTGRESQL LOCKING</strong></div><ArrowDown /><b>ONE WINNER</b></div><p>Configure a fresh target and execute a real attack to populate this result surface.</p></section>}</>
}

function AttackStat({ label, value, tone }) { return <div className={`attack-stat ${tone}`}><strong>{value}</strong><span>{label}</span></div> }

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
  const metricsQuery = useQuery({ queryKey: ['factory-metrics'], queryFn: getFactoryMetrics, refetchInterval: 2000 })
  const runtimeQuery = useQuery({ queryKey: ['factory-runtime'], queryFn: getFactoryRuntime, refetchInterval: 10000 })
  const latestId = metricsQuery.data?.latest_run?.id
  const timelineQuery = useQuery({ queryKey: ['factory-timeline', latestId], queryFn: () => getFactoryTimeline(latestId), enabled: Boolean(latestId), refetchInterval: 1500 })
  return <><PageHeading eyebrow="FACTORY RUN / 2026.10.02" title="A recorded execution" detail="Every stage is visible. Nothing here implies live agent activity." action={<StatusBadge status="VERIFIED" />} /><section className="run-summary"><div><span className="section-kicker">OBJECTIVE</span><h2>Validate a reservation system under pressure.</h2><p>Schema integrity, time correctness, idempotent retries, and concurrent booking behavior were tested against PostgreSQL.</p></div><div className="run-facts"><span><small>CURRENT STAGE</small><strong>HUMAN ACCEPTANCE</strong></span><span><small>AGENT ACTIVITY</small><strong>RECORDED</strong></span><span><small>DATABASE</small><strong>POSTGRESQL · 5439</strong></span></div></section><section className="content-section"><div className="section-title"><div><span className="section-kicker">EXECUTION GRAPH</span><h2>From objective to proof</h2></div></div><div className="large-pipeline">{stages.map(([name, role, status, description], index) => <div className={`run-stage ${status === 'PASS' ? 'stage-pass' : status === 'PENDING' ? 'stage-pending' : ''}`} key={name}><div className="run-stage-index">0{index + 1}</div><div className="run-stage-main"><div><strong>{name}</strong><span>{role}</span></div><p>{description}</p></div><StatusBadge status={status} />{index < stages.length - 1 && <div className="vertical-connector" />}</div>)}</div></section><section className="two-column"><div className="panel"><div className="panel-heading"><div><span className="section-kicker">OUTPUTS</span><h3>Evidence generated</h3></div></div><EvidenceMini name="factory_final_verification.md" detail="Final stage matrix" /><EvidenceMini name="breaker_concurrency.md" detail="Repeated attack results" /><EvidenceMini name="final_test_run.txt" detail="46 test execution log" /></div><div className="panel callout-panel"><TerminalSquare size={20} /><h3>Recorded, not live</h3><p>This run is grounded in files under <code>evidence/</code>. Live backend calls are available in the Reservation Lab.</p><NavLink to="/evidence" className="outline-link">Browse evidence <ArrowUpRight size={15} /></NavLink></div></section><section className="content-section"><div className="section-title"><div><span className="section-kicker">REAL RECORD / LATEST RUN</span><h2>Where the task is handed next</h2></div><span className="recorded-label">READ FROM THE DATABASE</span></div>{latestId ? <AgentHandoffChain timeline={timelineQuery.data} runtime={runtimeQuery.data} /> : <div className="inline-note"><AlertTriangle size={14} /> No factory run has been recorded yet. Start one from a project page to see the real hand-off chain.</div>}</section></>
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
  const ensureTable = async (tableId) => { try { await createTable({ table_id: tableId, capacity: 4 }); return true } catch (err) { if (err.code === 'TABLE_EXISTS') return true; setTableMessage(formatApiError(err)); return false } }
  const submit = async (event) => { event.preventDefault(); setBusy(true); setError(null); setResult(null); try { setResult(await createReservation(form)) } catch (err) { if (err.code === 'UNKNOWN_TABLE') { setTableMessage(`Table ${form.table_id} does not exist yet. Provisioning it through POST /tables...`); if (await ensureTable(form.table_id)) { setResult(await createReservation(form)); setTableMessage(`${form.table_id} was provisioned with POST /tables and the reservation was accepted.`); return } } setError(formatApiError(err)) } finally { setBusy(false) } }
  const provision = async (tableId) => { setTableMessage(`Creating ${tableId}...`); try { await createTable({ table_id: tableId, capacity: 4 }); setTableMessage(`${tableId} is ready.`) } catch (err) { setTableMessage(err.code === 'TABLE_EXISTS' ? `${tableId} already exists.` : formatApiError(err)) } }
  const runAttack = async () => {
    setAttack((current) => ({ ...current, running: true, result: null }))
    const fire = async (windowStart, windowEnd) => {
      const key = `attack-${crypto.randomUUID?.() || Date.now()}`
      const payload = { ...form, table_id: form.table_id, start_time: windowStart, end_time: windowEnd, idempotency_key: key }
      const count = Math.max(2, Math.min(25, Number(attack.count) || 8))
      const responses = await Promise.all(Array.from({ length: count }, () => createReservationWithStatus(payload).then((response) => ({ status: response.status, body: response.data })).catch((err) => ({ status: err.status || 0, error: err }))))
      return { count, responses, missing: responses.filter((item) => item.status === 404).length }
    }
    let attempt
    try { attempt = await runBurstOnFreeWindow(form.table_id, form.start_time, form.end_time, fire) } catch (err) { setTableMessage(formatApiError(err)); setAttack((current) => ({ ...current, running: false })); return }
    const { count, responses, missing } = attempt
    const [nextStart, nextEnd] = shiftWindow(attempt.start, attempt.end, 1)
    update('start_time', nextStart)
    update('end_time', nextEnd)
    setTableMessage(`Availability confirmed for ${attempt.start}. Next burst starts at ${nextStart}.`)
    const summary = { sent: count, success: responses.filter((item) => item.status === 201).length, replay: responses.filter((item) => item.status === 200).length, conflicts: responses.filter((item) => item.status === 409).length, missing, failed: missing + responses.filter((item) => item.status === 0 || item.status >= 500).length, responses }
    setAttack({ count, running: false, result: summary })
  }
  return <><PageHeading eyebrow="RESERVATION LAB / LIVE API" title="Operate the engine" detail="Create real reservations against the FastAPI backend. Table provisioning and booking responses are never simulated." action={<span className="live-chip"><span className="pulse-dot" /> LIVE REQUESTS</span>} /><div className="lab-grid"><section className="panel reservation-form-panel"><div className="panel-heading"><div><span className="section-kicker">01 / RESERVATION</span><h3>Book a table</h3></div><Beaker size={19} /></div><form onSubmit={submit} className="form-grid"><Field label="Customer name" value={form.customer_name} onChange={(value) => update('customer_name', value)} /><Field label="Table ID" value={form.table_id} onChange={(value) => update('table_id', value)} /><Field label="Start time" type="text" value={form.start_time} onChange={(value) => update('start_time', value)} hint="ISO 8601 with offset" /><Field label="End time" type="text" value={form.end_time} onChange={(value) => update('end_time', value)} hint="ISO 8601 with offset" /><Field label="Idempotency key" value={form.idempotency_key} onChange={(value) => update('idempotency_key', value)} wide hint="Reuse this key to observe a real 200 replay." /><button className="primary-button wide" disabled={busy}>{busy ? <><RefreshCw className="spin" size={16} /> Sending...</> : <><Play size={15} /> Create reservation</>}</button></form>{error && <ErrorBox message={error} />}</section><section className="panel table-panel"><div className="panel-heading"><div><span className="section-kicker">TARGETS</span><h3>Table registry</h3></div><span className="recorded-label">CHECKED BEFORE EVERY BURST</span></div><p className="panel-note">Provision a known target through the real <code>POST /tables</code> route. <code>GET /tables/&#123;id&#125;/availability</code> confirms a window is unbooked before any burst fires.</p><div className="table-grid">{['t1', 't2', 't3', 't4'].map((id, index) => <button className={`table-card ${form.table_id === id ? 'selected' : ''}`} key={id} onClick={() => update('table_id', id)}><span className="table-number">0{index + 1}</span><strong>{id.toUpperCase()}</strong><small>CAPACITY 4</small><span className="table-action" onClick={(event) => { event.stopPropagation(); provision(id) }}><Plus size={13} /> provision</span></button>)}</div>{tableMessage && <div className="inline-note"><Check size={14} /> {tableMessage}</div>}{result && <ReservationCard result={result} />}</section></div><section className="content-section attack-section"><div className="section-title"><div><span className="section-kicker">02 / CONCURRENCY ATTACK</span><h2>Put PostgreSQL under pressure</h2><p>All requests use one real idempotency key. The results below are from this browser session.</p></div><span className="recorded-label">PERSISTENT TEST DATA</span></div><div className="attack-console"><div className="attack-controls"><Field label="Requests" type="number" value={attack.count} onChange={(value) => setAttack((current) => ({ ...current, count: value }))} hint="2–25 per run" /><button className="primary-button" onClick={runAttack} disabled={attack.running}>{attack.running ? <><RefreshCw className="spin" size={16} /> Running...</> : <><Zap size={16} /> Run concurrency test</>}</button></div>{attack.result ? <div className="attack-result"><div className="attack-result-head"><div><span className="section-kicker">LIVE RESULT</span><h3>{attack.result.sent} requests completed</h3></div><StatusBadge status={attack.result.failed ? 'DEGRADED' : 'PASS'} /></div><div className="attack-metrics"><MetricCard label="Requests sent" value={attack.result.sent} detail="Real HTTP calls" icon={Activity} /><MetricCard label="Initial success" value={attack.result.success} detail="201 created" icon={Check} /><MetricCard label="Idempotent replay" value={attack.result.replay} detail="200 same row" icon={LockKeyhole} tone="blue" /><MetricCard label="Conflicts" value={attack.result.conflicts} detail="409 responses" icon={ShieldCheck} tone="amber" /><MetricCard label="Failed requests" value={attack.result.failed} detail="404 missing table or 5xx" icon={AlertTriangle} tone={attack.result.failed ? 'amber' : 'blue'} /></div><div className="attack-footnote"><Database size={15} /> The database invariant can be checked in the backend evidence; this UI has no delete route and intentionally labels test data as persistent.</div></div> : <div className="attack-empty"><div className="attack-flow"><span>{attack.count || 8} REQUESTS</span><ChevronRight /><span className="flow-core"><Database size={17} /> POSTGRESQL</span><ChevronRight /><strong>ONE WINNER</strong></div><p>Run the attack to replace this diagram with actual response counts.</p></div>}</div></section></>
}

function Field({ label, value, onChange, type = 'text', hint, wide = false }) { return <label className={`field ${wide ? 'wide' : ''}`}><span>{label}</span><input aria-label={label} type={type} value={value} onChange={(event) => onChange(event.target.value)} required={label !== 'Requests'} /><small>{hint || ' '}</small></label> }
function ReservationCard({ result }) {
  const [retrieved, setRetrieved] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const retrieve = async () => { setLoading(true); setError(''); try { setRetrieved(await getReservation(result.reservation_id)) } catch (requestError) { setError(formatApiError(requestError)) } finally { setLoading(false) } }
  return <div className="reservation-card"><div className="reservation-card-head"><div><span className="section-kicker">API RESPONSE</span><h3>Reservation accepted</h3></div><StatusBadge status={result.status?.toUpperCase() || 'ACTIVE'} /></div><div className="detail-grid"><Detail label="Reservation ID" value={result.reservation_id} mono /><Detail label="Table" value={result.table_id} /><Detail label="Start" value={result.start_time} mono /><Detail label="End" value={result.end_time} mono /><Detail label="Created" value={result.created_at} mono /><Detail label="Status" value={result.status} /></div><button className="outline-link retrieve-button" onClick={retrieve} disabled={loading}>{loading ? <><RefreshCw className="spin" size={14} /> Retrieving...</> : <><Server size={14} /> Retrieve by ID</>}</button>{retrieved && <div className="retrieve-result"><Check size={14} /> GET /reservations/{result.reservation_id} returned the same reservation.</div>}{error && <div className="error-box"><AlertTriangle size={14} />{error}</div>}</div>
}
function Detail({ label, value, mono }) { return <div className="detail-item"><small>{label}</small><strong className={mono ? 'mono' : ''}>{value}</strong></div> }
function ErrorBox({ message }) { return <div className="error-box"><AlertTriangle size={16} /><span>{message}</span></div> }
function formatApiError(error) { if (error.name === 'AbortError') return 'The API request timed out. Check that FastAPI is running.'; if (error.code === 'NO_FREE_WINDOW') return error.message; if (!error.status) return 'Backend unavailable. Start FastAPI on the configured API URL.'; if (error.code === 'OVERLAP_CONFLICT') return 'Reservation rejected: this table is already reserved for that time window.'; if (error.code === 'IDEMPOTENCY_PAYLOAD_MISMATCH') return 'This idempotency key is already bound to a different payload.'; if (error.code === 'UNKNOWN_TABLE') { const missing = /^table (.+) does not exist$/.exec(error.message || '')?.[1] || error.message; return `The backend has no table "${missing}" yet. Provision it through POST /tables first.` }; return error.message }

function IdempotencyLab() {
  const [state, setState] = useState({ running: false, first: null, replay: null, mismatch: null, error: null })
  const run = async () => {
    setState({ running: true, first: null, replay: null, mismatch: null, error: null })
    const suffix = crypto.randomUUID?.() || Date.now()
    const table = `idem-${String(suffix).slice(0, 12)}`
    const key = `idem-key-${suffix}`
    const payload = { customer_name: 'Idempotency observer', table_id: table, start_time: '2026-06-03T18:00:00+00:00', end_time: '2026-06-03T19:00:00+00:00', idempotency_key: key }
    try {
      await createTable({ table_id: table, capacity: 2 })
      const first = await createReservationWithStatus(payload)
      const replay = await createReservationWithStatus(payload)
      const mismatch = await createReservationWithStatus({ ...payload, customer_name: 'Changed payload' }).catch((error) => ({ status: error.status || 0, data: { error: error.code || error.message } }))
      setState({ running: false, first, replay, mismatch, error: null })
    } catch (error) { setState({ running: false, first: null, replay: null, mismatch: null, error: formatApiError(error) }) }
  }
  return <><PageHeading eyebrow="IDEMPOTENCY LAB / LIVE API" title="Same key. Same row." detail="A real three-step sequence: create, replay, then reuse the key with a different payload." action={<span className="live-chip"><span className="pulse-dot" /> LIVE REQUESTS</span>} /><div className="lab-intro"><div className="lab-intro-icon"><LockKeyhole size={21} /></div><div><h2>Retries should be boring.</h2><p>The first request creates. An identical retry returns the same reservation with HTTP 200. A changed payload is rejected without moving the stored row.</p></div><button className="primary-button" onClick={run} disabled={state.running}>{state.running ? <><RefreshCw className="spin" size={16} /> Running...</> : <><Play size={15} /> Run sequence</>}</button></div>{state.error && <ErrorBox message={state.error} />}{state.first && <div className="idempotency-sequence"><IdemStep number="01" label="First request" status={state.first.status} detail="New reservation created" result={state.first.data} /><div className="sequence-arrow"><ChevronRight /></div><IdemStep number="02" label="Identical replay" status={state.replay.status} detail="Same reservation ID returned" result={state.replay.data} /><div className="sequence-arrow"><ChevronRight /></div><IdemStep number="03" label="Different payload" status={state.mismatch.status} detail="Stored row remains unchanged" result={state.mismatch.data} /></div>}</>
}

function IdemStep({ number, label, status, detail, result }) { return <div className={`idem-step ${status === 201 ? 'created' : status === 200 ? 'replayed' : 'rejected'}`}><span className="step-number">{number}</span><span className="section-kicker">HTTP {status}</span><h3>{label}</h3><p>{detail}</p><strong>{result?.reservation_id || result?.error || 'No response body'}</strong></div> }

function TimezoneLab() {
  const [offset, setOffset] = useState('+02:00')
  const [state, setState] = useState({ running: false, response: null, error: null })
  const run = async () => { setState({ running: true, response: null, error: null }); const suffix = crypto.randomUUID?.() || Date.now(); const table = `tz-${String(suffix).slice(0, 12)}`; const start = `2026-06-04T20:00:00${offset}`; const end = `2026-06-04T21:00:00${offset}`; try { await createTable({ table_id: table, capacity: 2 }); const response = await createReservationWithStatus({ customer_name: 'Timezone observer', table_id: table, start_time: start, end_time: end, idempotency_key: `tz-key-${suffix}` }); setState({ running: false, response: { ...response, clientStart: start, clientEnd: end }, error: null }) } catch (error) { setState({ running: false, response: null, error: formatApiError(error) }) } }
  return <><PageHeading eyebrow="TIMEZONE LAB / LIVE API" title="One instant, many clocks." detail="Send an offset-bearing timestamp and inspect the UTC-normalized response returned by the real backend." action={<span className="live-chip"><span className="pulse-dot" /> LIVE REQUESTS</span>} /><div className="timezone-panel panel"><div className="timezone-controls"><div><span className="section-kicker">CLIENT OFFSET</span><h2>Choose a representation</h2></div><select value={offset} onChange={(event) => setOffset(event.target.value)} aria-label="Timezone offset"><option value="+00:00">UTC +00:00</option><option value="+01:00">UTC +01:00</option><option value="+03:00">UTC +03:00</option><option value="-05:00">UTC -05:00</option><option value="-08:00">UTC -08:00</option></select><button className="primary-button" onClick={run} disabled={state.running}>{state.running ? <><RefreshCw className="spin" size={16} /> Sending...</> : <><Clock3 size={15} /> Normalize timestamp</>}</button></div>{state.error && <ErrorBox message={state.error} />}{state.response ? <div className="timezone-result"><div className="time-column"><span className="section-kicker">CLIENT TIME</span><strong>{state.response.clientStart}</strong><strong>{state.response.clientEnd}</strong></div><div className="timezone-arrow"><ArrowUpRight size={20} /><small>backend normalizes</small></div><div className="time-column normalized"><span className="section-kicker">RETURNED UTC</span><strong>{state.response.data.start_time}</strong><strong>{state.response.data.end_time}</strong></div></div> : <div className="timezone-empty"><Clock3 size={20} /><p>Run a real request to see the instant collapse into UTC.</p></div>}</div><div className="panel timezone-note"><ShieldCheck size={17} /><p><strong>Invariant I6</strong> Different timezone representations of the same instant must represent the same instant. The API stores `timestamptz` and always returns an explicit UTC offset.</p></div></>
}

function AgentPipeline() {
  const metricsQuery = useQuery({ queryKey: ['factory-metrics'], queryFn: getFactoryMetrics, refetchInterval: 2000 })
  const runtimeQuery = useQuery({ queryKey: ['factory-runtime'], queryFn: getFactoryRuntime, refetchInterval: 10000 })
  const latestId = metricsQuery.data?.latest_run?.id
  const timelineQuery = useQuery({ queryKey: ['factory-timeline', latestId], queryFn: () => getFactoryTimeline(latestId), enabled: Boolean(latestId), refetchInterval: 1500 })
  const eventsQuery = useQuery({ queryKey: ['factory-events', latestId], queryFn: () => getFactoryEvents(latestId), enabled: Boolean(latestId), refetchInterval: 1500 })
  const runtime = runtimeQuery.data
  const timeline = timelineQuery.data
  const totals = metricsQuery.data?.totals
  const live = timeline?.execution_mode === 'live'
  return <><PageHeading eyebrow="AGENT PIPELINE / LIVE" title="Five roles. One proof chain." detail="Every card below is read from the running pipeline in the database. Nothing on this page is recorded or simulated." action={<span className={`live-chip${runtime?.available ? '' : ' offline'}`}><span className="pulse-dot" /> {runtime?.available ? 'AGENTS ONLINE' : 'RUNTIME OFFLINE'}</span>} />{runtime && <div className="run-state-grid"><Detail label="Runtime" value={`${runtime.provider_id}/${runtime.model_id}`} mono /><Detail label="Reachable" value={runtime.available ? 'yes' : 'no'} /><Detail label="Stage budget" value={`${runtime.timeout_seconds}s`} /><Detail label="Repair rounds" value={String(runtime.max_repair_rounds)} /></div>}{!runtime?.available && <div className="inline-note"><AlertTriangle size={14} /> No agent runtime is reachable. New runs will use the templated pipeline and will be labelled as such.</div>}<AgentHandoffChain timeline={timeline} runtime={runtime} />{totals && <div className="metrics-grid"><MetricCard label="Factory runs" value={String(totals.runs)} detail={`${totals.live_runs} with live agents`} icon={GitBranch} /><MetricCard label="Agent tasks" value={String(totals.tasks)} detail="hand-offs recorded" icon={Sparkles} /><MetricCard label="Artifacts" value={String(totals.artifacts)} detail="hashed outputs" icon={FileCheck2} /><MetricCard label="Human approvals" value={String(totals.approved)} detail={`${totals.approvals} requested`} icon={ShieldCheck} tone="blue" /></div>}{timeline && <section className="panel"><div className="panel-heading"><div><span className="section-kicker">LATEST RUN</span><h3>{timeline.run.current_stage}</h3></div><StatusBadge status={timeline.run.status.toUpperCase()} /></div><div className="run-state-grid"><Detail label="Run" value={timeline.run.id} mono /><Detail label="Mode" value={timeline.execution_mode} /><Detail label="Tasks" value={String(timeline.tasks.length)} /><Detail label="Approval" value={timeline.approval?.status || 'none'} /></div>{timeline.run.error && <ErrorBox message={timeline.run.error} />}<div className="agent-handoff-outputs">{(timeline.artifacts || []).map((artifact) => <div className="agent-chain-body" key={artifact.path}><strong>{artifact.artifact_type}</strong> <code>{artifact.path}</code><small className="agent-session">sha256 {String(artifact.sha256).slice(0, 16)}…</small></div>)}</div></section>}<section className="panel"><div className="panel-heading"><div><span className="section-kicker">LIVE HAND-OFF FEED</span><h3>Agent activity</h3></div>{live && <StatusBadge status="STREAMING" />}</div><div className="factory-events">{(eventsQuery.data || []).slice(-40).reverse().map((event) => <div className="factory-event" key={event.id}><span /><div><strong>{event.message}</strong><small>{event.stage} · {event.event_type}{event.agent_role ? ` · ${event.agent_role}` : ''} · {event.created_at}</small></div></div>)}</div></section></>
}

function EvidenceCenter() { const [selected, setSelected] = useState(evidenceItems[0]); const [query, setQuery] = useState(''); const filtered = useMemo(() => evidenceItems.filter((item) => `${item.name} ${item.summary}`.toLowerCase().includes(query.toLowerCase())), [query]); const copy = () => navigator.clipboard?.writeText(selected.content); return <><PageHeading eyebrow="EVIDENCE CENTER / BUILD-TIME MANIFEST" title="Proof, in full view" detail="These documents are imported from the repository's real evidence directory at build time." action={<span className="recorded-label"><FileCheck2 size={14} /> SOURCE: /evidence</span>} /><div className="evidence-layout"><section className="panel evidence-list"><div className="search-box"><Activity size={15} /><input placeholder="Filter evidence" value={query} onChange={(event) => setQuery(event.target.value)} /></div>{filtered.map((item) => <button className={`evidence-list-item ${selected.name === item.name ? 'selected' : ''}`} key={item.name} onClick={() => setSelected(item)}><div><strong>{item.name}</strong><small>{item.type} · {item.summary}</small></div><StatusBadge status={item.status} /></button>)}</section><section className="panel evidence-viewer"><div className="viewer-head"><div><span className="section-kicker">{selected.type}</span><h3>{selected.name}</h3></div><button className="icon-button" title="Copy evidence" onClick={copy}><Copy size={16} /></button></div><pre>{selected.content}</pre></section></div></> }

function Health({ backendStatus }) { return <><PageHeading eyebrow="SYSTEM HEALTH / OBSERVED" title="Know what is online" detail="Only the API status is actively measured. Database status is not exposed by the current backend and is intentionally unknown." action={<button className="quiet-button" onClick={() => window.location.reload()}><RefreshCw size={15} /> Recheck</button>} /><div className="health-grid"><HealthCard label="Frontend" status="ONLINE" detail="Vite application rendered in this browser." icon={Gauge} /><HealthCard label="Backend API" status={backendStatus === 'ONLINE' ? 'ONLINE' : backendStatus} detail="Measured with a real HTTP probe against FastAPI." icon={Server} /><HealthCard label="Database" status="UNKNOWN" detail="No public health route; PostgreSQL is not guessed from the UI." icon={Database} /></div><div className="panel health-panel"><div className="panel-heading"><div><span className="section-kicker">CONNECTION DETAILS</span><h3>Runtime configuration</h3></div></div><div className="detail-grid"><Detail label="API base URL" value={apiBaseUrl} mono /><Detail label="Probe route" value="GET /docs" mono /><Detail label="Interpretation" value="HTTP < 500 = API reachable" /></div></div></> }
function HealthCard({ label, status, detail, icon: Icon }) { return <div className="health-card"><div className="health-icon"><Icon size={20} /></div><div><span>{label}</span><h2>{status}</h2><p>{detail}</p></div><span className={`health-dot ${status.toLowerCase()}`} /></div> }

function GitHubSettings() {
  const queryClient = useQueryClient()
  const [newRepo, setNewRepo] = useState({ name: '', private: true, description: '' })
  const statusQuery = useQuery({ queryKey: ['github-status'], queryFn: getGitHubStatus, retry: false })
  const connected = statusQuery.data?.status === 'CONNECTED'
  const repositoriesQuery = useQuery({ queryKey: ['github-repositories'], queryFn: getGitHubRepositories, enabled: connected, retry: false })
  const installationsQuery = useQuery({ queryKey: ['github-installations'], queryFn: getGitHubInstallations, enabled: connected, retry: false })
  const createRepository = useMutation({
    mutationFn: createGitHubRepository,
    onSuccess: () => {
      setNewRepo({ name: '', private: true, description: '' })
      queryClient.invalidateQueries({ queryKey: ['github-repositories'] })
    },
  })
  const status = statusQuery.data?.status || (statusQuery.error?.status === 503 ? 'NOT_CONFIGURED' : statusQuery.isPending ? 'CHECKING' : 'ERROR')
  const capabilities = statusQuery.data?.capabilities || {}
  const repositories = repositoriesQuery.data?.repositories || []
  const installations = installationsQuery.data?.installations || []

  return <>
    <PageHeading eyebrow="SETTINGS / INTEGRATIONS / GITHUB" title="GitHub, without guesswork." detail="Every value on this page is returned by the backend GitHub App service against the real GitHub API. Credentials stay on the server; the browser never holds a token or private key." action={<StatusBadge status={status} />} />
    <div className="github-status-grid">
      <section className="panel settings-panel">
        <div className="panel-heading"><div><span className="section-kicker">GITHUB APP</span><h3>Installation status</h3></div><Github size={19} /></div>
        <div className="github-status-main">
          <div className={`github-status-icon ${status.toLowerCase()}`}><Github size={25} /></div>
          <div><strong>{status.replaceAll('_', ' ')}</strong><p>{statusQuery.data?.message || statusQuery.error?.message || 'Checking the real GitHub API connection.'}</p></div>
        </div>
        {statusQuery.data && <div className="detail-grid detail-grid-wide">
          <Detail label="App" value={statusQuery.data.app_name} />
          <Detail label="Installation ID" value={statusQuery.data.installation_id || 'None recorded'} mono />
          <Detail label="Account" value={statusQuery.data.account ? `${statusQuery.data.account.login} (${statusQuery.data.account.type})` : 'No installation account'} />
          <Detail label="Repository selection" value={statusQuery.data.repository_selection || 'Not reported by GitHub'} />
        </div>}
        <div className="capability-row">{Object.entries(capabilities).map(([key, value]) => <span key={key} className={`capability-chip ${value ? 'on' : 'off'}`}>{key.replaceAll('_', ' ')}</span>)}</div>
        <div className="action-row">
          {statusQuery.data?.install_url && <a className="primary-button" href={statusQuery.data.install_url} target="_blank" rel="noreferrer"><Github size={15} /> {connected ? 'Manage installation on GitHub' : 'Install the App on GitHub'}</a>}
          <button className="quiet-button" onClick={() => { statusQuery.refetch(); repositoriesQuery.refetch(); installationsQuery.refetch() }}><RefreshCw size={15} /> Refresh</button>
        </div>
        <div className="boundary"><CircleHelp size={14} /><span>Installation happens on github.com. This page then reports what the real API returns. Required server values are documented in <code>docs/github-app-setup.md</code>.</span></div>
      </section>
      <section className="panel settings-panel">
        <div className="panel-heading"><div><span className="section-kicker">INSTALLATIONS</span><h3>Recorded from signed webhooks</h3></div><Link2 size={18} /></div>
        {installations.length ? installations.map((installation) => <div className="settings-row" key={installation.installation_id}>
          <div><strong>{installation.account_login || 'Unknown account'}</strong><small>Installation {installation.installation_id} · {installation.account_type || 'unknown type'} · {installation.repository_selection || 'selection not reported'}</small></div>
          <StatusBadge status={(installation.status || 'unknown').toUpperCase()} />
        </div>) : <EmptyState title="No installation recorded" detail={connected ? 'The installation is active but no signed webhook has been received yet.' : 'Install the App on GitHub, then set the webhook secret so installations are recorded automatically.'} />}
      </section>
    </div>
    <div className="github-status-grid">
      <section className="panel settings-panel">
        <div className="panel-heading"><div><span className="section-kicker">REPOSITORIES</span><h3>{connected ? `${repositories.length} accessible through the installation` : 'Waiting for connection'}</h3></div><Database size={18} /></div>
        {repositories.length ? repositories.map((repository) => <div className="settings-row" key={repository.id}>
          <div><strong>{repository.full_name}</strong><small>{repository.private ? 'Private' : 'Public'} · default {repository.default_branch || 'unknown'}{repository.archived ? ' · archived' : ''}</small></div>
          <StatusBadge status={repository.archived ? 'ARCHIVED' : 'CONNECTED'} />
        </div>) : <EmptyState title="No repository data" detail={connected ? 'The installation returned no repositories.' : 'Repository listing is unavailable until a real App installation is configured.'} />}
      </section>
      <section className="panel settings-panel">
        <div className="panel-heading"><div><span className="section-kicker">CREATE REPOSITORY</span><h3>{capabilities.create_repository ? 'Organization repositories' : 'Unavailable for this installation'}</h3></div><Plus size={18} /></div>
        {capabilities.create_repository ? <>
          <div className="form-grid">
            <label className="field wide"><span>Repository name</span><input value={newRepo.name} onChange={(event) => setNewRepo({ ...newRepo, name: event.target.value })} placeholder="nairobytes-client-site" /></label>
            <label className="field wide"><span>Description</span><input value={newRepo.description} onChange={(event) => setNewRepo({ ...newRepo, description: event.target.value })} placeholder="Generated by the Dark Factory" /></label>
            <label className="field wide"><span>Visibility</span><select value={newRepo.private ? 'private' : 'public'} onChange={(event) => setNewRepo({ ...newRepo, private: event.target.value === 'private' })}><option value="private">Private</option><option value="public">Public</option></select></label>
          </div>
          <div className="action-row">
            <button className="primary-button" disabled={createRepository.isPending || !newRepo.name.trim()} onClick={() => createRepository.mutate({ ...newRepo, name: newRepo.name.trim() })}>
              {createRepository.isPending ? <RefreshCw className="spin" size={15} /> : <Plus size={15} />} Create on GitHub
            </button>
            <span className="recorded-label">{statusQuery.data?.account?.login}</span>
          </div>
          {createRepository.isError && <ErrorBox message={formatApiError(createRepository.error)} />}
          {createRepository.data && <div className="github-result"><Check size={13} /> Created {createRepository.data.full_name}</div>}
          <div className="boundary"><CircleHelp size={14} /><span>GitHub only allows an App installation token to create repositories inside an organization, so personal installations are rejected by the backend instead of being simulated.</span></div>
        </> : <EmptyState title="Organization installations only" detail={connected ? 'GitHub does not allow an App installation token to create repositories on a personal account.' : 'Connect an organization installation to enable repository creation.'} />}
      </section>
    </div>
  </>
}

const publishableRunStates = ['awaiting_approval', 'approved']

function GitHubProject() {
  const { projectId } = useParams()
  const queryClient = useQueryClient()
  const [selectedRepository, setSelectedRepository] = useState('')
  const projectQuery = useQuery({ queryKey: ['project', projectId], queryFn: () => getProject(projectId), retry: false })
  const statusQuery = useQuery({ queryKey: ['github-status'], queryFn: getGitHubStatus, retry: false })
  const stateQuery = useQuery({ queryKey: ['project-github', projectId], queryFn: () => getProjectGitHub(projectId), retry: false })
  const repositoriesQuery = useQuery({ queryKey: ['github-repositories'], queryFn: getGitHubRepositories, enabled: statusQuery.data?.status === 'CONNECTED', retry: false })
  const repositories = repositoriesQuery.data?.repositories || []
  const repository = repositories.find((item) => String(item.id) === selectedRepository)
  const mapping = stateQuery.data?.mapping
  const latestRun = stateQuery.data?.latest_run
  const runId = latestRun?.id
  const commits = stateQuery.data?.commits || []
  const runCommits = commits.filter((commit) => commit.factory_run_id === runId)
  const published = runCommits.length > 0
  const pullRequestQuery = useQuery({ queryKey: ['project-pull-request', projectId, runId], queryFn: () => getProjectPullRequest(projectId, runId), enabled: Boolean(runId) && published, retry: false })

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['project-github', projectId] })
  const connect = useMutation({
    mutationFn: () => connectProjectGitHub(projectId, {
      repository_id: repository.id,
      owner: repository.owner || String(repository.full_name).split('/')[0],
      repository_name: repository.name,
      default_branch: repository.default_branch || 'main',
      installation_id: statusQuery.data.installation_id,
    }),
    onSuccess: () => { setSelectedRepository(''); refresh() },
  })
  const disconnect = useMutation({ mutationFn: () => disconnectProjectGitHub(projectId), onSuccess: refresh })
  const publish = useMutation({ mutationFn: () => publishProjectRun(projectId, runId), onSuccess: refresh })
  const openPullRequest = useMutation({ mutationFn: () => createProjectPullRequest(projectId, runId), onSuccess: () => { refresh(); queryClient.invalidateQueries({ queryKey: ['project-pull-request', projectId, runId] }) } })
  const refreshPullRequest = useMutation({ mutationFn: () => getProjectPullRequest(projectId, runId), onSuccess: () => queryClient.invalidateQueries({ queryKey: ['project-pull-request', projectId, runId] }) })

  const mutationError = connect.error || disconnect.error || publish.error || openPullRequest.error || refreshPullRequest.error
  const pullRequest = pullRequestQuery.data
  const publishable = publishableRunStates.includes(latestRun?.status)

  return <>
    <PageHeading eyebrow={`PROJECT / ${projectQuery.data?.slug || projectId} / GITHUB`} title="Publish verified work." detail="Link this project to a repository the GitHub App installation can reach, push the real generated files onto a factory branch, and open a real pull request from it." action={<NavLink className="quiet-button" to={`/projects/${projectId}`}><ChevronRight size={15} /> Project</NavLink>} />
    {mutationError && <ErrorBox message={formatApiError(mutationError)} />}
    <div className="github-status-grid">
      <section className="panel settings-panel">
        <div className="panel-heading"><div><span className="section-kicker">REPOSITORY LINK</span><h3>{stateQuery.data?.linked ? 'Linked repository' : 'No repository linked'}</h3></div><Github size={19} /></div>
        {stateQuery.data?.linked && mapping ? <>
          <div className="detail-grid detail-grid-wide">
            <Detail label="Repository" value={`${mapping.owner}/${mapping.repository_name}`} mono />
            <Detail label="Default branch" value={mapping.default_branch} mono />
            <Detail label="Installation" value={mapping.installation_id} mono />
            <Detail label="Link status" value={mapping.status} />
          </div>
          <div className="action-row"><button className="quiet-button" disabled={disconnect.isPending} onClick={() => disconnect.mutate()}><Unlink size={15} /> Disconnect</button></div>
        </> : <>
          <div className="form-grid">
            <label className="field wide"><span>Repository from the installation</span>
              <select value={selectedRepository} onChange={(event) => setSelectedRepository(event.target.value)}>
                <option value="">{repositories.length ? 'Select a repository' : 'No repositories available'}</option>
                {repositories.map((item) => <option key={item.id} value={item.id}>{item.full_name}{item.private ? ' (private)' : ''}</option>)}
              </select>
            </label>
          </div>
          <div className="action-row">
            <button className="primary-button" disabled={!repository || connect.isPending} onClick={() => connect.mutate()}>{connect.isPending ? <RefreshCw className="spin" size={15} /> : <Link2 size={15} />} Link repository</button>
            {connect.data && <span className="recorded-label">LINKED {connect.data.owner}/{connect.data.repository_name}</span>}
          </div>
          <div className="boundary"><CircleHelp size={14} /><span>The backend re-reads the repository from GitHub and rejects a mismatch between the selected repository and the installation token before anything is stored.</span></div>
        </>}
      </section>
      <section className="panel settings-panel">
        <div className="panel-heading"><div><span className="section-kicker">LATEST FACTORY RUN</span><h3>{latestRun ? `Run ${String(runId).slice(0, 8)}` : 'No factory run'}</h3></div><GitBranch size={18} /></div>
        {latestRun ? <>
          <div className="detail-grid detail-grid-wide">
            <Detail label="Run status" value={latestRun.status} />
            <Detail label="Current stage" value={latestRun.current_stage || 'Not recorded'} />
            <Detail label="Branch" value={runCommits[0]?.branch || 'Not pushed yet'} mono />
            <Detail label="Commit" value={runCommits[0]?.commit_hash || 'Not pushed yet'} mono />
          </div>
          <div className="action-row">
            <button className="primary-button" disabled={!stateQuery.data?.linked || !publishable || publish.isPending} onClick={() => publish.mutate()}>
              {publish.isPending ? <RefreshCw className="spin" size={15} /> : <Upload size={15} />} Push to factory branch
            </button>
            <span className="recorded-label">{publishable ? 'RUN IS PUBLISHABLE' : 'RUN MUST BE VERIFIED'}</span>
          </div>
          {publish.data && <div className="github-result"><Check size={13} /> {publish.data.status === 'NO_CHANGES' ? 'No file changes to push' : `Pushed ${publish.data.files_changed.length} files to ${publish.data.branch}`}</div>}
          <div className="boundary"><CircleHelp size={14} /><span>Only verified runs ({publishableRunStates.join(' or ')}) can be published. The default branch is never modified; generated files land on <code>factory/project-{'{project_id}'}/run-{'{run_id}'}</code>.</span></div>
        </> : <EmptyState title="No factory run yet" detail="Start a factory run for this project before publishing anything to GitHub." action={<NavLink to={`/factory`} className="outline-link">Open Factory Run</NavLink>} />}
      </section>
    </div>
    <div className="github-status-grid">
      <section className="panel settings-panel">
        <div className="panel-heading"><div><span className="section-kicker">PULL REQUEST</span><h3>{pullRequest ? `#${pullRequest.number} ${pullRequest.title || ''}` : 'No pull request yet'}</h3></div><GitPullRequest size={18} /></div>
        {pullRequest && <div className="detail-grid detail-grid-wide">
          <Detail label="State" value={pullRequest.state || pullRequest.status} />
          <Detail label="Merged" value={pullRequest.merged ? 'YES' : 'NO'} />
          <Detail label="Head" value={pullRequest.head_ref || pullRequest.source_branch} mono />
          <Detail label="Base" value={pullRequest.base_ref || pullRequest.target_branch} mono />
          <Detail label="Changed files" value={pullRequest.changed_files ?? 'Not reported'} />
          <Detail label="Commits" value={pullRequest.commits ?? 'Not reported'} />
        </div>}
        <div className="action-row">
          <button className="primary-button" disabled={!published || openPullRequest.isPending} onClick={() => openPullRequest.mutate()}>
            {openPullRequest.isPending ? <RefreshCw className="spin" size={15} /> : <GitPullRequest size={15} />} Open pull request
          </button>
          <button className="quiet-button" disabled={!pullRequest || refreshPullRequest.isPending} onClick={() => refreshPullRequest.mutate()}><RefreshCw size={15} /> Refresh from GitHub</button>
          {pullRequest?.url && <a className="outline-link" href={pullRequest.url} target="_blank" rel="noreferrer">Open on GitHub <ArrowUpRight size={14} /></a>}
        </div>
        {pullRequestQuery.isError && <ErrorBox message={formatApiError(pullRequestQuery.error)} />}
        <div className="boundary"><CircleHelp size={14} /><span>The pull request body is generated from the real recorded tasks, artifacts, files, commit, and approval state for this run.</span></div>
      </section>
      <section className="panel settings-panel">
        <div className="panel-heading"><div><span className="section-kicker">PUSH HISTORY</span><h3>{commits.length} recorded push{commits.length === 1 ? '' : 'es'}</h3></div><TerminalSquare size={18} /></div>
        {commits.length ? commits.map((commit) => <div className="settings-row" key={commit.id}>
          <div><strong>{commit.branch}</strong><small>{String(commit.commit_hash || '').slice(0, 12)} · {(commit.files_changed || []).length} files · {commit.pushed_at || commit.created_at}</small></div>
          <StatusBadge status="PUSHED" />
        </div>) : <EmptyState title="Nothing pushed yet" detail="Every real push to GitHub is recorded here with its branch, commit, and file list." />}
      </section>
    </div>
  </>
}

function Settings() { return <><PageHeading eyebrow="SETTINGS / LOCAL CONSOLE" title="Configuration, made visible." detail="This console has no secret settings or hidden server state. These values are the actual local runtime contract." /><div className="settings-grid"><section className="panel settings-panel"><div className="panel-heading"><div><span className="section-kicker">FRONTEND RUNTIME</span><h3>Connection profile</h3></div><Settings2 size={18} /></div><div className="settings-row"><div><strong>API base URL</strong><small>Loaded from VITE_API_BASE_URL</small></div><code>{apiBaseUrl}</code></div><div className="settings-row"><div><strong>Frontend mode</strong><small>Vite development server</small></div><span className="recorded-label">LOCAL</span></div><div className="settings-row"><div><strong>Evidence source</strong><small>Imported at build time from repository files</small></div><span className="recorded-label">/evidence</span></div></section><section className="panel settings-panel"><div className="panel-heading"><div><span className="section-kicker">BOUNDARIES</span><h3>What this UI will not invent</h3></div><ShieldCheck size={18} /></div><Boundary text="Database health is UNKNOWN without a backend health route." /><Boundary text="Tables are provisioned through the real POST /tables route." /><Boundary text="Agent activity is RECORDED, not presented as live." /><Boundary text="Reservation demos create persistent test data because no delete route exists." /></section></div></> }
function Boundary({ text }) { return <div className="boundary"><Check size={14} /><span>{text}</span></div> }

function About() { return <><PageHeading eyebrow="ABOUT / THE METHOD" title="Software engineering, reimagined as a factory." detail="A system for turning objectives into software that has survived its own attack." /><section className="about-hero"><span className="section-kicker">THE CORE PRINCIPLE</span><h2>AI agents do not simply generate code.<br /><em>They produce software, challenge it, repair it, and prove it.</em></h2></section><div className="method-grid">{[['01', 'Human', 'Defines the objective and remains the final authority.'], ['02', 'Architect', 'Maps requirements, invariants, risks, and acceptance tests.'], ['03', 'Builder', 'Implements the smallest working system and verifies it.'], ['04', 'Breaker', 'Attacks assumptions with adversarial, reproducible tests.'], ['05', 'Repair', 'Fixes root causes only when a genuine defect appears.'], ['06', 'Verifier', 'Independently checks the result before human acceptance.']].map(([number, title, copy]) => <div className="method-step" key={number}><span>{number}</span><h3>{title}</h3><p>{copy}</p></div>)}</div></> }

export default App