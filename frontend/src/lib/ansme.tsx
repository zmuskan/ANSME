import { Link, useNavigate } from "@tanstack/react-router";
import { motion } from "motion/react";
import { Bell, Check, ChevronRight, Clock3, Download, Headphones, History, Home, Menu, Plus, Search, Settings, ShieldCheck, Sparkles, Trash2, Trophy, X } from "lucide-react";
import { createContext, type Dispatch, type FormEvent, type ReactNode, type SetStateAction, useContext, useEffect, useMemo, useState } from "react";
import { analyzeProduct, deleteHistoryItem, getHistory, type HistoryRecord, type SuccessfulProduct } from "@/lib/api";
import authAsset from "@/assets/01_auth_background.mp4";
import authWebmAsset from "@/assets/01_auth_background.webm";
import workspaceAsset from "@/assets/02_workspace_background.png";
import analyzingAsset from "@/assets/03_analyzing_background.png";
import resultAsset from "@/assets/04_result_background.png";
import comparisonAsset from "@/assets/05_comparison_background.png";
import historyAsset from "@/assets/06_history_background.png";
import settingsAsset from "@/assets/07_settings_background.png";

export interface AnalysisRequest { urls: string[]; budget: string; requirements: string }
export type SingleResult = SuccessfulProduct;
export interface ComparisonResult { products: Array<{ name: string; price: string; pros: string[]; cons: string[] }>; winner: string; why: string; bestFor: string }
export interface HistoryItem { id: string; title: string; date: string; verdict: string; price: string }
export interface UserSettings { saveHistory: boolean; personalizedAdvice: boolean; notifications: boolean; theme: "system" | "dark" }

type AppState = { request: AnalysisRequest; setRequest: (r: AnalysisRequest) => void; result: SingleResult | null; setResult: (r: SingleResult) => void; comparison: ComparisonResult | null; setComparison: (c: ComparisonResult) => void; history: HistoryItem[]; setHistory: Dispatch<SetStateAction<HistoryItem[]>>; settings: UserSettings; setSettings: (s: UserSettings) => void };
const AppContext = createContext<AppState | undefined>(undefined);
export function AppProvider({ children }: { children: ReactNode }) {
  const [request, setRequest] = useState<AnalysisRequest>({ urls: [], budget: "", requirements: "" });
  const [result, setResult] = useState<SingleResult | null>(null);
  const [comparison, setComparison] = useState<ComparisonResult | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [settings, setSettings] = useState<UserSettings>({ saveHistory: true, personalizedAdvice: true, notifications: false, theme: "dark" });
  const value = useMemo(() => ({ request, setRequest, result, setResult, comparison, setComparison, history, setHistory, settings, setSettings }), [request, result, comparison, history, settings]);
  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}
export function useAnsme() { const value = useContext(AppContext); if (!value) throw new Error("ANSME provider missing"); return value; }

const backgrounds = { workspace: workspaceAsset, analyzing: analyzingAsset, result: resultAsset, comparison: comparisonAsset, history: historyAsset, settings: settingsAsset };
export function Screen({ name, children, nav = true, scroll = false }: { name: keyof typeof backgrounds; children: ReactNode; nav?: boolean; scroll?: boolean }) {
  return <main className={`ansme-screen ${scroll ? "screen-scroll" : "overflow-hidden"}`}><div className="portrait-stage"><img className="screen-art" src={backgrounds[name]} alt="" /><div className="screen-shade" />{nav && <Nav />}<div className="screen-content">{children}</div></div></main>;
}
function Nav() {
  const [open, setOpen] = useState(false);
  return <><button className="icon-button nav-trigger" onClick={() => setOpen(true)} aria-label="Open navigation"><Menu /></button>{open && <motion.aside initial={{ x: -280 }} animate={{ x: 0 }} exit={{ x: -280 }} className="nav-drawer"><button className="icon-button self-end" onClick={() => setOpen(false)} aria-label="Close navigation"><X /></button><p className="brand">ANSME</p><nav><Link to="/workspace" onClick={() => setOpen(false)}><Home className="size-5" />Home</Link><Link to="/history" onClick={() => setOpen(false)}><History className="size-5" />History</Link><Link to="/settings" onClick={() => setOpen(false)}><Settings className="size-5" />Settings</Link></nav></motion.aside>}<Link to="/workspace" className="avatar" aria-label="New analysis"><Plus className="size-5" /></Link></>;
}
export function AuthScreen() {
  return <main className="ansme-screen overflow-hidden"><div className="portrait-stage"><video className="screen-art" autoPlay muted loop playsInline><source src={authWebmAsset} type="video/webm" /><source src={authAsset} type="video/mp4" /></video><div className="auth-overlay"><Link to="/workspace" className="action-button google-button"><span className="google-g">G</span> Continue with Google</Link><Link to="/workspace" className="action-button guest-button">Continue as Guest</Link><div className="trust-line"><span><ShieldCheck className="size-4" />Research first. Regret less.</span><small>No spam. No bore. Just decisions.</small></div></div></div></main>;
}
export function WorkspaceScreen() {
  const navigate = useNavigate(); const { request, setRequest, setResult, setComparison } = useAnsme(); const [urls, setUrls] = useState<string[]>(request.urls.length ? request.urls : [""]); const [loading, setLoading] = useState(false); const [error, setError] = useState<string | null>(null);
  function updateUrl(index: number, value: string) { setUrls((current) => current.map((url, urlIndex) => urlIndex === index ? value : url)); }
  function addUrl() { setUrls((current) => current.length < 3 ? [...current, ""] : current); }
  function removeUrl(index: number) { setUrls((current) => current.filter((_, urlIndex) => urlIndex !== index)); }
  async function submit(e: FormEvent) {
    e.preventDefault();
    const validUrls = urls.map((url) => url.trim()).filter(Boolean);
    if (!validUrls.length) return;
    const firstUrl = validUrls[0];
    if (!firstUrl) return;

    setRequest({ ...request, urls: validUrls });
    setError(null);
    setLoading(true);

    try {
      const budget = parseBudget(request.budget);
      if (validUrls.length === 1) {
        const result = await analyzeProduct(firstUrl, budget, request.requirements);
        console.log(result);
        const product = result.products[0];
        if (!product || product.status !== "success") {
          throw new Error(product?.status === "error" ? product.error : "No product was analyzed.");
        }
        setResult(product);
        navigate({ to: "/result" });
        return;
      }

      const products = await Promise.all(validUrls.map(async (productUrl) => {
        const result = await analyzeProduct(productUrl, budget, request.requirements);
        console.log(result);
        const product = result.products[0];
        if (!product || product.status !== "success") {
          throw new Error(product?.status === "error" ? product.error : `No result for ${productUrl}.`);
        }
        return product;
      }));
      const firstProduct = products[0];
      if (!firstProduct) throw new Error("No products were analyzed.");
      setResult(firstProduct);
      const winner = products.reduce((best, product) => product.overall_score > best.overall_score ? product : best);
      setComparison({
        products: products.map((product) => ({
          name: product.title || product.url,
          price: formatPrice(product.price),
          pros: product.analysis.pros,
          cons: product.analysis.cons,
        })),
        winner: winner.title || winner.url,
        why: winner.analysis.explanation,
        bestFor: `Requirement match: ${winner.analysis.requirement_match}/10`,
      });
      navigate({ to: "/comparison" });
    } catch (err) {
      console.error(err);
      setError(err instanceof Error ? err.message : "Analysis failed. Please try again.");
    } finally {
      setLoading(false);
    }
  }
  const examples: { label: string; url: string }[] = [];
  return <Screen name="workspace"><motion.form initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="glass-panel workspace-panel" onSubmit={submit}><div className="panel-heading"><p className="eyebrow">New analysis</p><h1>What are you thinking of buying?</h1></div><fieldset className="url-fieldset"><legend>Product URL{urls.length > 1 ? "s" : ""}</legend>{urls.map((url, index) => <div className="input-row" key={index}><input type="url" required value={url} onChange={(e) => updateUrl(index, e.target.value)} placeholder={`Paste product URL ${index + 1}`} aria-label={`Product URL ${index + 1}`} />{index === 0 && urls.length < 3 ? <button type="button" className="icon-button add-url" onClick={addUrl} aria-label="Add another product URL"><Plus /></button> : index > 0 ? <button type="button" className="icon-button" onClick={() => removeUrl(index)} aria-label={`Remove product URL ${index + 1}`}><X /></button> : null}</div>)}</fieldset><div className="chips" aria-label="Examples">{examples.map((example) => <button key={example.label} type="button" onClick={() => updateUrl(0, example.url)}>{example.label}</button>)}</div><label>Budget<input value={request.budget} onChange={(e) => setRequest({ ...request, budget: e.target.value })} placeholder="e.g. Under ₹10,000" /></label><label>What matters most?<textarea value={request.requirements} onChange={(e) => setRequest({ ...request, requirements: e.target.value })} placeholder="Comfort, durability, battery life…" /></label>{error && <p className="analysis-error" role="alert">{error}</p>}<button className="action-button primary-action" type="submit" disabled={loading}><Sparkles className="size-5" />{loading ? "Analyzing…" : urls.length > 1 ? "Compare" : "Analyze"}</button></motion.form></Screen>;
}
function parseBudget(value: string): number | undefined {
  const normalized = value.trim().toLowerCase().replace(/,/g, "");
  if (!normalized) return undefined;
  const match = normalized.match(/(\d+(?:\.\d+)?)\s*(k|m)?/);
  if (!match) throw new Error("Enter a numeric budget, such as 10000 or 10k.");
  const multiplier = match[2] === "k" ? 1_000 : match[2] === "m" ? 1_000_000 : 1;
  const budget = Number(match[1]) * multiplier;
  if (!Number.isFinite(budget) || budget <= 0) throw new Error("Budget must be greater than zero.");
  return budget;
}
function formatPrice(price: number | null): string {
  return price === null ? "Price unavailable" : price.toLocaleString();
}
export function AnalyzingScreen() {
  const navigate = useNavigate(); const { request } = useAnsme(); const [step, setStep] = useState(0); const items = ["Fetching product details", "Reading reviews", "Finding common complaints", "Checking requirements", "Generating verdict"];
  useEffect(() => { const timer = window.setInterval(() => setStep((current) => Math.min(current + 1, items.length)), 750); return () => window.clearInterval(timer); }, [items.length]);
  useEffect(() => { if (step === items.length) navigate({ to: request.urls.length >= 2 ? "/comparison" : "/result" }); }, [items.length, navigate, request.urls.length, step]);
  return <Screen name="analyzing" nav={false}><motion.section initial={{ opacity: 0, scale: .98 }} animate={{ opacity: 1, scale: 1 }} className="glass-panel analyzing-panel"><div className="loading-mark"><Search /></div><p className="eyebrow">Evidence check</p><h1>{step < 3 ? "Reading between the stars…" : "Building your verdict…"}</h1><div className="checklist">{items.map((item, index) => <motion.div key={item} animate={{ opacity: index <= step ? 1 : .42 }}><span className={index < step ? "done" : index === step ? "current" : ""}>{index < step ? <Check /> : index + 1}</span>{item}</motion.div>)}</div></motion.section></Screen>;
}
export function ResultScreen() {
  const { result } = useAnsme();
  if (!result) {
    return <Screen name="result"><div className="glass-panel">No analysis available.</div></Screen>;
  }
  return <Screen name="result" scroll><motion.section initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="glass-panel result-panel"><p className="eyebrow">ANSME verdict</p><div className="verdict">{result.verdict.toUpperCase()}</div><p className="confidence">{result.overall_score.toFixed(1)}/10 overall score</p><div className="result-head"><div className="product-thumb"><Headphones /></div><div><h1>{result.title}</h1><a href={result.url} target="_blank" rel="noreferrer">View product <ChevronRight /></a></div><strong>{formatPrice(result.price)}</strong></div><p className="result-summary">{result.analysis.explanation}</p><div className="result-grid"><Info title="The good stuff" items={result.analysis.pros} positive /><Info title="The catches" items={result.analysis.cons} /></div><div className="friend-note"><strong>Sentiment</strong><p>{result.analysis.sentiment_score}/10</p><strong>Requirements match</strong><p>{result.analysis.requirement_match}/10</p>{result.analysis.risk_flags.length > 0 && <><strong>Risks</strong><p>{result.analysis.risk_flags.join(", ")}</p></>}</div><Link className="action-button primary-action" to="/workspace">Analyze another</Link></motion.section></Screen>;
}
function Info({ title, items, text, positive }: { title: string; items?: string[]; text?: string; positive?: boolean }) { return <div className="info-block"><h2>{title}</h2>{items ? <ul>{items.map((item) => <li key={item}><span>{positive ? "+" : "−"}</span>{item}</li>)}</ul> : <p>{text}</p>}</div>; }
export function ComparisonScreen() { const { comparison } = useAnsme(); if (!comparison) { return <Screen name="comparison"><div className="glass-panel">No comparison available.</div></Screen>; } return <Screen name="comparison" scroll><section className="glass-panel comparison-panel"><p className="eyebrow">Head-to-head</p><h1>Same vibe. Different price. <span>Which one wins?</span></h1><div className={`product-duel products-${comparison.products.length}`}>{comparison.products.map((product) => <article key={product.name}><div className="compare-image" role="img" aria-label={`${product.name} product image`}><Headphones /></div><h2>{product.name}</h2><strong className="compare-price">{product.price}</strong><div className="compare-points"><div><b>Pros</b>{product.pros.map((item) => <small key={item}>+ {item}</small>)}</div><div><b>Cons</b>{product.cons.map((item) => <small key={item}>− {item}</small>)}</div></div></article>)}</div><div className="winner"><Trophy /><div><small>ANSME PICK</small><strong>{comparison.winner}</strong><dl><dt>Why it wins</dt><dd>{comparison.why}</dd><dt>Best for</dt><dd>{comparison.bestFor}</dd></dl></div></div><Link className="action-button primary-action" to="/workspace">Analyze another</Link></section></Screen>; }
export function HistoryScreen() {
  const { history, setHistory } = useAnsme();
  const [search, setSearch] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function loadHistory() {
      try {
        const data = await getHistory();
        if (!cancelled) {
          setHistory(data.map(mapHistoryRecord));
        }
      } catch (err) {
        console.error(err);
        if (!cancelled) {
          setError("Unable to load analysis history.");
        }
      }
    }

    void loadHistory();
    return () => {
      cancelled = true;
    };
  }, [setHistory]);

  async function handleDelete(id: string) {
    try {
      await deleteHistoryItem(Number(id));
      setHistory((current) => current.filter((item) => item.id !== id));
    } catch (err) {
      console.error(err);
      setError("Unable to delete this analysis.");
    }
  }

  const filtered = history.filter((item) => item.title.toLowerCase().includes(search.toLowerCase()));
  return <Screen name="history" scroll><section className="glass-panel history-panel"><p className="eyebrow">Decision archive</p><h1>Your past calls</h1><label className="search-box"><Search /><input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search analyses" /></label>{error && <p className="analysis-error" role="alert">{error}</p>}<div className="history-list">{filtered.map((item) => <article key={item.id}><div><small><Clock3 />{item.date}</small><h2>{item.title}</h2><p>{item.price}</p></div><div><span className={`verdict-badge ${item.verdict.toLowerCase().replace(" ", "-")}`}>{item.verdict}</span><Link to="/result">Reopen <ChevronRight /></Link><button type="button" className="icon-button" aria-label={`Delete ${item.title}`} onClick={() => void handleDelete(item.id)}><Trash2 /></button></div></article>)}</div><Link to="/workspace" className="action-button primary-action"><Plus />New analysis</Link></section></Screen>;
}

function mapHistoryRecord(item: HistoryRecord): HistoryItem {
  return {
    id: String(item.id),
    title: item.title ?? item.url,
    date: new Date(item.created_at).toLocaleDateString(),
    verdict: item.verdict,
    price: item.price === null ? "Price unavailable" : `₹${item.price.toLocaleString("en-IN")}`,
  };
}
const legal = { privacy: { title: "Privacy", body: "Your product links and preferences are used only to create your analysis. You control whether analysis history is saved." }, terms: { title: "Terms", body: "ANSME provides research-based guidance, not a guarantee. Prices, availability, and product details may change." }, disclaimer: { title: "Disclaimer", body: "Verdicts are informational and should be one input in your decision. Always review current seller terms and safety guidance." } };
export function SettingsScreen() { const { settings, setSettings } = useAnsme(); const [tab, setTab] = useState<"settings" | keyof typeof legal>("settings"); return <Screen name="settings" scroll><section className="glass-panel settings-panel"><div className="tabs">{(["settings", "privacy", "terms", "disclaimer"] as const).map((name) => <button key={name} className={tab === name ? "active" : ""} onClick={() => setTab(name)}>{name}</button>)}</div>{tab === "settings" ? <><p className="eyebrow">Your rules</p><h1>Settings</h1><div className="setting-list"><Toggle label="Save analysis history" value={settings.saveHistory} onChange={(value) => setSettings({ ...settings, saveHistory: value })} /><Toggle label="Personalized advice" value={settings.personalizedAdvice} onChange={(value) => setSettings({ ...settings, personalizedAdvice: value })} /><Toggle label="Notifications" value={settings.notifications} onChange={(value) => setSettings({ ...settings, notifications: value })} icon={<Bell />} /><label className="theme-row"><span>Theme preference</span><select value={settings.theme} onChange={(e) => setSettings({ ...settings, theme: e.target.value as UserSettings["theme"] })}><option value="dark">Dark</option><option value="system">Use device setting</option></select></label></div><div className="data-actions"><button type="button"><Download />Export data</button><button type="button" className="danger-action"><Trash2 />Delete data</button></div><p className="privacy-note"><ShieldCheck />Your data, your call.</p></> : <motion.div key={tab} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="legal-copy"><p className="eyebrow">ANSME</p><h1>{legal[tab].title}</h1><p>{legal[tab].body}</p><p>We keep our language clear, collect only what the experience needs, and never sell personal information.</p></motion.div>}</section></Screen>; }
function Toggle({ label, value, onChange, icon }: { label: string; value: boolean; onChange: (value: boolean) => void; icon?: ReactNode }) { return <label className="toggle-row"><span>{icon}{label}</span><button type="button" role="switch" aria-checked={value} aria-label={label} className={value ? "on" : ""} onClick={() => onChange(!value)}><span /></button></label>; }
