import { Link, useNavigate } from "@tanstack/react-router";
import { jsPDF } from "jspdf";
import { motion } from "motion/react";
import { CartesianGrid, Cell, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Bell, Check, ChevronRight, Clock3, Download, Headphones, History, Home, Menu, Plus, Search, Settings, ShieldCheck, Sparkles, Trash2, Trophy, X } from "lucide-react";
import { createContext, type Dispatch, type FormEvent, type ReactNode, type SetStateAction, useContext, useEffect, useMemo, useState } from "react";
import { analyzeProduct, deleteHistoryItem, getAllHistory, getAnalytics, getHistoryItem, getLeaderboard, getLeaderboardParticipation, setLeaderboardParticipation, type AnalyticsSummary, type HistoryRecord, type LeaderboardItem, type SuccessfulProduct } from "@/lib/api";
import { deleteHistoryRecords } from "@/lib/history-actions";
import { signInAsGuest, signInWithGoogle, useAuth } from "@/lib/auth";
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
export interface ComparisonResult { products: SuccessfulProduct[] }
export interface HistoryItem { id: string; title: string; url: string; date: string; verdict: string; price: string; score: number }
export interface UserSettings { saveHistory: boolean; personalizedAdvice: boolean; notifications: boolean; shareToLeaderboard: boolean; theme: "system" | "dark" | "light" }

type AppState = { request: AnalysisRequest; setRequest: (r: AnalysisRequest) => void; result: SingleResult | null; setResult: (r: SingleResult) => void; comparison: ComparisonResult | null; setComparison: (c: ComparisonResult) => void; history: HistoryItem[]; setHistory: Dispatch<SetStateAction<HistoryItem[]>>; settings: UserSettings; setSettings: Dispatch<SetStateAction<UserSettings>> };
const AppContext = createContext<AppState | undefined>(undefined);
export function AppProvider({ children }: { children: ReactNode }) {
  const [request, setRequest] = useState<AnalysisRequest>({ urls: [], budget: "", requirements: "" });
  const [result, setResult] = useState<SingleResult | null>(null);
  const [comparison, setComparison] = useState<ComparisonResult | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [settings, setSettings] = useState<UserSettings>(() => {
    const defaults: UserSettings = {
      saveHistory: true,
      personalizedAdvice: true,
      notifications: false,
      shareToLeaderboard: false,
      theme: readSavedTheme(),
    };

    if (typeof window === "undefined") return defaults;

    try {
      const saved = window.localStorage.getItem("ansme.settings");
      if (!saved) return defaults;

      const parsed = JSON.parse(saved) as Partial<UserSettings>;

      return {
        ...defaults,
        ...parsed,
        theme:
          parsed.theme === "light" ||
          parsed.theme === "dark" ||
          parsed.theme === "system"
            ? parsed.theme
            : defaults.theme,
      };
    } catch {
      return defaults;
    }
  });
  useEffect(() => {
    const root = document.documentElement;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const applyTheme = () => {
      const dark = settings.theme === "dark" || (settings.theme === "system" && media.matches);
      root.classList.toggle("dark", dark);
      root.classList.toggle("light", !dark);
    };
    applyTheme();
    if (settings.theme === "system") {
      media.addEventListener("change", applyTheme);
    }
    try {
      window.localStorage.setItem("theme", settings.theme);
    } catch (error) {
      console.error("Unable to persist theme preference.", error);
    }
    return () => media.removeEventListener("change", applyTheme);
  }, [settings.theme]);
  useEffect(() => {
    try {
      window.localStorage.setItem("ansme.settings", JSON.stringify(settings));
    } catch (error) {
      console.error("Unable to persist settings.", error);
    }
  }, [settings]);
  const value = useMemo(() => ({ request, setRequest, result, setResult, comparison, setComparison, history, setHistory, settings, setSettings }), [request, result, comparison, history, settings]);
  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}
export function useAnsme() { const value = useContext(AppContext); if (!value) throw new Error("ANSME provider missing"); return value; }
function readSavedTheme(): UserSettings["theme"] {
  if (typeof window === "undefined") return "dark";
  try {
    const saved = window.localStorage.getItem("theme");
    return saved === "light" || saved === "system" ? saved : "dark";
  } catch (error) {
    console.error("Unable to read saved theme preference.", error);
    return "dark";
  }
}

const backgrounds = { workspace: workspaceAsset, analyzing: analyzingAsset, result: resultAsset, comparison: comparisonAsset, history: historyAsset, settings: settingsAsset };
export function Screen({ name, children, nav = true, scroll = false }: { name: keyof typeof backgrounds; children: ReactNode; nav?: boolean; scroll?: boolean }) {
  return <main className="ansme-screen"><div className="app-stage"><img className="screen-art" src={backgrounds[name]} alt="" /><div className="screen-shade" />{nav && <Nav />}<div className="screen-content">{children}</div></div></main>;
}
function Nav() {
  const [open, setOpen] = useState(false);
  return <><button className="icon-button nav-trigger" onClick={() => setOpen(true)} aria-label="Open navigation"><Menu /></button>{open && <motion.aside initial={{ x: -280 }} animate={{ x: 0 }} exit={{ x: -280 }} className="nav-drawer"><button className="icon-button self-end" onClick={() => setOpen(false)} aria-label="Close navigation"><X /></button><p className="brand">ANSME</p><nav><Link to="/workspace" onClick={() => setOpen(false)}><Home className="size-5" />Home</Link><Link to="/history" onClick={() => setOpen(false)}><History className="size-5" />History</Link><Link to="/leaderboard" onClick={() => setOpen(false)}><Trophy className="size-5" />Leaderboard</Link><Link to="/settings" onClick={() => setOpen(false)}><Settings className="size-5" />Settings</Link></nav></motion.aside>}<Link to="/workspace" className="avatar" aria-label="New analysis"><Plus className="size-5" /></Link></>;
}
export function AuthScreen() {
  const navigate = useNavigate();
  const { status, error: authError } = useAuth();
  const [signInMethod, setSignInMethod] = useState<"google" | "guest" | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (status === "authenticated") {
      void navigate({ to: "/workspace", replace: true });
    }
  }, [navigate, status]);

  const handleGoogleSignIn = async () => {
    setSignInMethod("google");
    setError(null);
    try {
      await signInWithGoogle();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Google sign-in failed. Please try again.");
      setSignInMethod(null);
    }
  };

  const handleGuestSignIn = async () => {
    setSignInMethod("guest");
    setError(null);
    try {
      const session = await signInAsGuest();
      if (!session.user || !session.access_token) {
        throw new Error("Guest sign-in did not return a valid session.");
      }
      await navigate({ to: "/workspace" });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Guest sign-in failed. Please try again.");
      setSignInMethod(null);
    }
  };

  return <main className="ansme-screen overflow-hidden"><div className="portrait-stage"><video className="screen-art" autoPlay muted loop playsInline><source src={authWebmAsset} type="video/webm" /><source src={authAsset} type="video/mp4" /></video><div className="auth-overlay"><button type="button" className="action-button google-button" onClick={() => void handleGoogleSignIn()} disabled={signInMethod !== null}><span className="google-g">G</span> {signInMethod === "google" ? "Signing in…" : "Continue with Google"}</button><button type="button" className="action-button guest-button" onClick={() => void handleGuestSignIn()} disabled={signInMethod !== null}>{signInMethod === "guest" ? "Signing in…" : "Continue as Guest"}</button>{(error || authError) && <p className="analysis-error" role="alert">{error ?? authError?.message}</p>}<div className="trust-line"><span><ShieldCheck className="size-4" />Research first. Regret less.</span><small>No spam. No bore. Just decisions.</small></div></div></div></main>;
}
export function WorkspaceScreen() {
  const navigate = useNavigate(); const { request, setRequest, setResult, setComparison, result, settings } = useAnsme(); const [urls, setUrls] = useState<string[]>(request.urls.length ? request.urls : [""]); const [loading, setLoading] = useState(false); const [error, setError] = useState<string | null>(null); const [analytics, setAnalytics] = useState<AnalyticsSummary | null>(null); const [analyticsDays, setAnalyticsDays] = useState<number | undefined>(30);

  useEffect(() => {
    const loadAnalytics = async () => {
      try {
        const data = await getAnalytics(analyticsDays);
        setAnalytics(data);
      } catch (err) {
        console.error(err);
      }
    };

    void loadAnalytics();
  }, [analyticsDays]);

  const handleExportReport = () => {
    if (!result) {
      return;
    }

    const doc = new jsPDF();
    doc.text(result.title ?? result.url, 10, 10);
    doc.text(result.verdict, 10, 20);
    doc.text(`Overall score: ${result.overall_score.toFixed(1)}/10`, 10, 30);
    if (result.analysis?.explanation) {
      const lines = doc.splitTextToSize(result.analysis.explanation, 180);
      doc.text(lines, 10, 40);
    }
    doc.save("analysis.pdf");
  };

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
        const result = await analyzeProduct(firstUrl, budget, request.requirements, settings.saveHistory);
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
        const result = await analyzeProduct(productUrl, budget, request.requirements, settings.saveHistory);
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
      setComparison({ products });
      navigate({ to: "/comparison" });
    } catch (err) {
      console.error(err);
      setError(err instanceof Error ? err.message : "Analysis failed. Please try again.");
    } finally {
      setLoading(false);
    }
  }
  const examples: { label: string; url: string }[] = [];
  const verdictData = analytics ? [
    { name: "Worth It", value: analytics.worth_it_count, color: "#4ade80" },
    { name: "Consider", value: analytics.consider_count, color: "#facc15" },
    { name: "Skip", value: analytics.skip_count, color: "#fb7185" },
  ] : [];
  return <Screen name="workspace"><div className="workspace-layout">
    <motion.form initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="glass-panel workspace-panel" onSubmit={submit}><div className="panel-heading"><p className="eyebrow">New analysis</p><h1>What are you thinking of buying?</h1></div><fieldset className="url-fieldset"><legend>Product URL{urls.length > 1 ? "s" : ""}</legend>{urls.map((url, index) => <div className="input-row" key={index}><input type="url" required value={url} onChange={(e) => updateUrl(index, e.target.value)} placeholder={`Paste product URL ${index + 1}`} aria-label={`Product URL ${index + 1}`} />{index === 0 && urls.length < 3 ? <button type="button" className="icon-button add-url" onClick={addUrl} aria-label="Add another product URL"><Plus /></button> : index > 0 ? <button type="button" className="icon-button" onClick={() => removeUrl(index)} aria-label={`Remove product URL ${index + 1}`}><X /></button> : null}</div>)}</fieldset><div className="chips" aria-label="Examples">{examples.map((example) => <button key={example.label} type="button" onClick={() => updateUrl(0, example.url)}>{example.label}</button>)}</div><label>Budget<input value={request.budget} onChange={(e) => setRequest({ ...request, budget: e.target.value })} placeholder="e.g. Under ₹10,000" /></label><label>What matters most?<textarea value={request.requirements} onChange={(e) => setRequest({ ...request, requirements: e.target.value })} placeholder="Comfort, durability, battery life…" /></label>{error && <p className="analysis-error" role="alert">{error}</p>}<button className="action-button primary-action" type="submit" disabled={loading}><Sparkles className="size-5" />{loading ? "Analyzing…" : urls.length > 1 ? "Compare" : "Analyze"}</button></motion.form>
    <section className="analytics-dashboard" aria-label="Analytics">
      <div className="glass-panel analytics-cards">
        <label className="analytics-filter">Analytics period<select value={analyticsDays ?? "all"} onChange={(event) => setAnalyticsDays(event.target.value === "all" ? undefined : Number(event.target.value))}><option value={7}>Last 7 Days</option><option value={30}>Last 30 Days</option><option value={90}>Last 90 Days</option><option value="all">All Time</option></select></label>
        <div className="mini-stat"><span>Total Analyses</span><strong>{analytics?.total_analyses ?? 0}</strong></div>
        <div className="mini-stat"><span>Average Credibility</span><strong>{analytics ? Number(analytics.avg_score).toFixed(1) : "0.0"}</strong></div>
        <div className="mini-stat"><span>Most Common Verdict</span><strong>{analytics ? (analytics.worth_it_count >= analytics.consider_count && analytics.worth_it_count >= analytics.skip_count ? "WORTH IT" : analytics.consider_count >= analytics.skip_count ? "CONSIDER" : "SKIP") : "—"}</strong></div>
        <div className="mini-stat"><span>Sources Analyzed</span><strong>{analytics?.sources_analyzed ?? 0}</strong></div>
      </div>
      <section className="glass-panel analytics-trend" aria-label="Analysis score trend">
        <h2>Score trend</h2>
        {analytics?.history.length ? <div className="h-56 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={analytics.history}>
              <CartesianGrid strokeDasharray="3 3" stroke="#52525b" />
              <XAxis dataKey="date" stroke="#a1a1aa" />
              <YAxis domain={[0, 10]} stroke="#a1a1aa" />
              <Tooltip />
              <Line type="monotone" dataKey="score" name="Average score" stroke="#4ade80" strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        </div> : <p>No saved analysis trend is available yet.</p>}
      </section>
      <section className="glass-panel verdict-distribution" aria-label="Verdict distribution">
        <h2>Verdict distribution</h2>
        {verdictData.some((item) => item.value > 0) ? <div className="h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie data={verdictData} dataKey="value" nameKey="name" outerRadius={85} label>
                {verdictData.map((item) => <Cell key={item.name} fill={item.color} />)}
              </Pie>
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        </div> : <p>No verdicts in this period.</p>}
      </section>
      <section className="glass-panel category-analytics">
        <h2>Product categories</h2>
        <p>Most analyzed: {analytics?.most_analyzed_category?.category ?? "No category data"}</p>
        {analytics?.categories.map((item) => <p key={item.category}>{item.category}: {item.count} analyses · average score {item.avg_score.toFixed(1)}</p>)}
        <h3>Top source domains</h3>
        {analytics?.top_sources.map((source) => <p key={source.domain}>{source.domain}: {source.count}</p>)}
      </section>
    </section>
  </div></Screen>;
}
function parseBudget(value: string): number | undefined {
  const normalized = value.trim().toLowerCase().replace(/,/g, "");
  if (!normalized) return undefined;
  const match = normalized.match(/(\d+(?:\.\d+)?)(k|m)?/);
  if (!match) throw new Error("Enter a numeric budget, such as 10000 or 10k.");
  const multiplier = match[2] === "k" ? 1_000 : match[2] === "m" ? 1_000_000 : 1;
  const budget = Number(match[1]) * multiplier;
  if (!Number.isFinite(budget) || budget <= 0) throw new Error("Budget must be greater than zero.");
  return budget;
}
function isCurrencyCode(currency?: string | null): currency is string {
  return typeof currency === "string" && /^[A-Za-z]{3}$/.test(currency.trim());
}

function currencyFromText(text: string): string | null {
  if (/\bINR\b|₹/i.test(text)) return "INR";
  if (/\bUSD\b|US\$/i.test(text)) return "USD";
  if (/\bEUR\b|€/i.test(text)) return "EUR";
  if (/\bGBP\b|£/i.test(text)) return "GBP";
  return null;
}

function formatPrice(
  price: number | null,
  currency?: string | null,
  rawPrice?: string | null,
): string {
  if (price === null) return "Price unavailable";
  if (!isCurrencyCode(currency)) {
    const amount = new Intl.NumberFormat("en", {
      maximumFractionDigits: 2,
    }).format(price);
    return `${amount} (currency unknown)`;
  }

  try {
    const locale =
      currency === "INR" ? "en-IN" :
      currency === "USD" ? "en-US" :
      currency === "GBP" ? "en-GB" :
      currency === "EUR" ? "de-DE" : "en";
    return new Intl.NumberFormat(locale, {
      style: "currency",
      currency,
      maximumFractionDigits: 2,
    }).format(price);
  } catch (error) {
    console.error(`Unable to format price in ${currency}.`, error);
    return `${rawPrice || price.toLocaleString("en")} (${currency})`;
  }
}
export function AnalyzingScreen() {
  const navigate = useNavigate(); const { request } = useAnsme(); const [step, setStep] = useState(0); const items = ["Fetching product details", "Reading reviews", "Finding common complaints", "Checking requirements", "Generating verdict"];
  useEffect(() => { const timer = window.setInterval(() => setStep((current) => Math.min(current + 1, items.length)), 750); return () => window.clearInterval(timer); }, [items.length]);
  useEffect(() => { if (step === items.length) navigate({ to: request.urls.length >= 2 ? "/comparison" : "/result" }); }, [items.length, navigate, request.urls.length, step]);
  return <Screen name="analyzing" nav={false}><motion.section initial={{ opacity: 0, scale: .98 }} animate={{ opacity: 1, scale: 1 }} className="glass-panel analyzing-panel"><div className="loading-mark"><Search /></div><p className="eyebrow">Evidence check</p><h1>{step < 3 ? "Reading between the stars…" : "Building your verdict…"}</h1><div className="checklist">{items.map((item, index) => <motion.div key={item} animate={{ opacity: index <= step ? 1 : .42 }}><span className={index < step ? "done" : index === step ? "current" : ""}>{index < step ? <Check /> : index + 1}</span>{item}</motion.div>)}</div></motion.section></Screen>;
}
export function ResultScreen() {
  const { result } = useAnsme();
  const [copyMessage, setCopyMessage] = useState("");

  async function copyAnalysis() {
    if (!result) return;
    try {
      await navigator.clipboard.writeText(JSON.stringify(result, null, 2));
      setCopyMessage("Analysis copied.");
    } catch (err) {
      console.error(err);
      setCopyMessage("Unable to copy analysis. Check clipboard permissions.");
    }
  }

  function downloadJson() {
    if (!result) return;
    const blob = new Blob([JSON.stringify(result, null, 2)], { type: "application/json" });
    const downloadUrl = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = downloadUrl;
    anchor.download = "ansme-analysis.json";
    anchor.click();
    URL.revokeObjectURL(downloadUrl);
  }

  if (!result) {
    return <Screen name="result"><div className="glass-panel">No analysis available.</div></Screen>;
  }
  const rawConfidence = result.metrics["confidence_score"];
  const confidence = typeof rawConfidence === "number"
    ? Math.max(0, Math.min(100, rawConfidence * 10))
    : null;
  const priceHistory = result.price_history?.history ?? [];
  const historyCurrency = result.price_history?.common_currency
    ?? priceHistory[0]?.price_currency
    ?? null;
  const historyCurrencyIsConsistent = isCurrencyCode(historyCurrency)
    && priceHistory.every((item) => item.price_currency?.toUpperCase() === historyCurrency.toUpperCase());
  const trend = priceHistory.length > 1 && historyCurrencyIsConsistent
    ? priceHistory.at(-1)!.price > priceHistory[0]!.price
      ? "Rising"
      : priceHistory.at(-1)!.price < priceHistory[0]!.price
        ? "Falling"
        : "Stable"
    : null;
  const evidenceByType = [
    ["Strengths", result.evidence.filter((item) => item.source.toLowerCase() === "strength")],
    ["Concerns", result.evidence.filter((item) => item.source.toLowerCase() === "concern")],
    ["Other evidence", result.evidence.filter((item) => !["strength", "concern"].includes(item.source.toLowerCase()))],
  ] as const;

  return <Screen name="result" scroll>
    <motion.section initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="glass-panel result-panel">
      {result.history_save_error && <p className="analysis-error" role="status">{result.history_save_error}</p>}
      <div className="result-hero">
        <div className="result-hero-copy">
          <p className="eyebrow">ANSME verdict</p>
          <div className="verdict">{result.verdict.toUpperCase()}</div>
          <p className="result-score">{result.overall_score.toFixed(1)}<span>/10 overall score</span></p>
          <a href={result.url} target="_blank" rel="noreferrer noopener">View product page <ChevronRight /></a>
        </div>
        <div className="result-hero-image">
          {result.image_url
            ? <img src={result.image_url} alt={result.title} />
            : <div className="no-image"><Headphones /><span>No product image provided</span></div>}
        </div>
        <div className="result-quick-facts">
          <div><span>Price</span><strong>{formatPrice(result.price, result.price_currency, result.price_raw)}</strong>
            {result.price_raw && <small>Source: {result.price_raw}</small>}
          </div>
          <div><span>Confidence</span><strong>{confidence === null ? "Unavailable" : `${confidence}%`}</strong>
            {confidence !== null && <div className="confidence-track"><i style={{ width: `${confidence}%` }} /></div>}
          </div>
        </div>
      </div>

      <p className="result-summary">{result.analysis.explanation}</p>
      <div className="result-grid">
        <Info title="The good stuff" items={result.analysis.pros} positive />
        <Info title="The catches" items={result.analysis.cons} />
      </div>

      <section className="result-section score-breakdown">
        <h2>What shaped the score</h2>
        <ScoreBreakdown result={result} />
      </section>

      <section className="result-section evidence-list">
        <h2>Evidence behind the call</h2>
        {result.evidence.length
          ? evidenceByType.map(([group, items]) => items.length > 0 && <section className="evidence-group" key={group}>
              <h3>{group}</h3>
              <div className="evidence-grid">{items.map((evidence, index) => <article key={`${evidence.source}-${evidence.url}-${index}`}>
                <strong>{evidence.title}</strong>
                <span>{evidence.source} · Evidence quality {evidence.quality_score}/100</span>
                <p>{evidence.snippet}</p>
                <a href={evidence.url} target="_blank" rel="noopener noreferrer">Open source <ChevronRight /></a>
              </article>)}</div>
            </section>)
          : <p className="empty-state">No evidence snippets were extracted from the available product page.</p>}
      </section>

      <section className="result-section price-history">
        <div className="section-heading"><div><h2>Price history</h2><p>Recorded observations for this product</p></div></div>
        <div className="price-summary">
          <div><span>Current</span><strong>{formatPrice(result.price, result.price_currency, result.price_raw)}</strong></div>
          <div><span>Lowest recorded</span><strong>{formatPrice(result.price_history?.lowest_seen ?? null, historyCurrencyIsConsistent ? historyCurrency : null)}</strong></div>
          <div><span>Highest recorded</span><strong>{formatPrice(result.price_history?.highest_seen ?? null, historyCurrencyIsConsistent ? historyCurrency : null)}</strong></div>
          <div><span>Trend</span><strong>{trend ?? (priceHistory.length < 2 ? "Not enough observations" : "Currencies not verified")}</strong></div>
        </div>
        {priceHistory.length > 1 && historyCurrencyIsConsistent
          ? <div className="price-chart">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={priceHistory} margin={{ top: 12, right: 18, bottom: 4, left: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#52525b" />
                  <XAxis dataKey="captured_at" tickFormatter={(value) => value ? new Date(value).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "Latest"} stroke="#a1a1aa" />
                  <YAxis tickFormatter={(value) => new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(Number(value))} stroke="#a1a1aa" width={54} />
                  <Tooltip formatter={(value) => formatPrice(Number(value), historyCurrency)} labelFormatter={(value) => value ? new Date(String(value)).toLocaleString() : "Latest observation"} />
                  <Line type="monotone" dataKey="price" name="Recorded price" stroke="#d946ef" strokeWidth={3} dot={{ fill: "#d946ef", r: 4 }} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          : <p className="empty-state">{priceHistory.length === 0
              ? "No price observations are available yet."
              : priceHistory.length === 1
                ? "Only one price observation is available. More observations are needed to show a trend."
                : "Price history spans unknown or different currencies, so a combined chart would be misleading."}</p>}
      </section>

      <details className="secondary-metadata">
        <summary>More analysis details</summary>
        <div className="metadata-grid">
          <p><span>Category</span>{result.category || "Unavailable"}</p>
          <p><span>Rating</span>{result.rating === null ? "Unavailable" : `${result.rating}/5`}</p>
          <p><span>Review count</span>{result.review_count === null ? "Unavailable" : result.review_count.toLocaleString()}</p>
          <p><span>Sources analyzed</span>{result.sources_analyzed}</p>
          <p><span>Requirements match</span>{result.analysis.requirement_match}/10</p>
          <p><span>Sentiment</span>{result.analysis.sentiment_score}/10</p>
          {result.analysis.risk_flags.length > 0 && <p><span>Risk flags</span>{result.analysis.risk_flags.join(", ")}</p>}
          {result.processing_time_ms !== null && <p><span>Processing time</span>{result.processing_time_ms} ms</p>}
        </div>
      </details>

      {result.similar_products?.length ? <section className="result-section similar-products">
        <h2>Previously analyzed products</h2>
        {result.similar_products.map((item) => <p key={item.id}><a href={item.url} target="_blank" rel="noopener noreferrer">{item.title || item.url}</a> · Score {item.overall_score.toFixed(1)}/10</p>)}
      </section> : null}

      <div className="result-actions">
        <button type="button" className="action-button" onClick={() => void copyAnalysis()}>Copy analysis</button>
        <button type="button" className="action-button" onClick={downloadJson}>Download JSON</button>
      </div>
      {copyMessage && <p role="status">{copyMessage}</p>}
      <Link className="action-button primary-action" to="/workspace">Analyze another</Link>
    </motion.section>
  </Screen>;
}
function Info({ title, items, positive }: { title: string; items: string[]; positive?: boolean }) {
  return <section className={`info-block${positive ? " positive" : " negative"}`}>
    <h2>{title}</h2>
    {items.length
      ? <ul>{items.map((item) => <li key={item}><span aria-hidden="true">{positive ? "+" : "−"}</span>{item}</li>)}</ul>
      : <p className="empty-state">Nothing notable was found in the available product details.</p>}
  </section>;
}

function ScoreBreakdown({ result }: { result: SuccessfulProduct }) {
  const metrics = [
    { key: "value_score", label: "Price & value", contribution: "Value contribution" },
    { key: "rating_score", label: "Customer rating", contribution: "Rating contribution" },
    { key: "confidence_score", label: "Data confidence", contribution: "Confidence contribution" },
  ].filter((item) => typeof result.metrics[item.key] === "number");
  if (!metrics.length) return <p className="empty-state">Score breakdown is unavailable for this analysis.</p>;
  return <div className="score-metrics">{metrics.map((item) => {
    const score = result.metrics[item.key] ?? 0;
    const contribution = result.score_breakdown[item.contribution];
    return <div className="score-metric" key={item.key}>
      <div className="score-metric-label"><strong>{item.label}</strong><span>{score.toFixed(1)}/10{typeof contribution === "number" ? ` · +${contribution.toFixed(2)} overall` : ""}</span></div>
      <div className="score-track" role="meter" aria-label={`${item.label} score`} aria-valuemin={0} aria-valuemax={10} aria-valuenow={score}><i style={{ width: `${Math.max(0, Math.min(100, score * 10))}%` }} /></div>
    </div>;
  })}<div className="score-total"><span>Deterministic overall score</span><strong>{result.overall_score.toFixed(1)} / 10</strong></div></div>;
}

function PriceValue({ product }: { product: SuccessfulProduct }) {
  return <span className="price-value">
    {formatPrice(product.price, product.price_currency, product.price_raw)}
    {product.price_raw && <small>Source: {product.price_raw}</small>}
  </span>;
}

function confidencePercent(product: SuccessfulProduct): number | null {
  const confidence = product.metrics["confidence_score"];
  return typeof confidence === "number"
    ? Math.max(0, Math.min(100, confidence * 10))
    : null;
}

export function ComparisonScreen() {
  const { comparison, request } = useAnsme();
  if (!comparison || comparison.products.length < 2) {
    return <Screen name="comparison"><div className="glass-panel">No comparison available.</div></Screen>;
  }
  const products = comparison.products;
  const ranked = [...products].sort((a, b) => b.overall_score - a.overall_score);
  const leader = ranked[0]!;
  const runnerUp = ranked[1]!;
  const scoreGap = leader.overall_score - runnerUp.overall_score;
  const tied = scoreGap <= 0.05;
  const leaderConfidence = confidencePercent(leader);
  const leaderConfidenceLabel = leaderConfidence === null ? "unavailable" : `${leaderConfidence}%`;
  const insufficientData = leaderConfidence === null || leaderConfidence < 70;
  const budgetText = request.budget.trim();
  const budgetCurrency = currencyFromText(budgetText);
  const budgetUnverified = budgetText.length > 0 && (
    !budgetCurrency
    || !products.every((product) =>
      product.price !== null
      && product.price_currency?.toUpperCase() === budgetCurrency,
    )
  );
  const selected = tied || insufficientData || budgetUnverified ? null : leader;
  const undecided = tied || insufficientData || budgetUnverified;
  const banner = tied
    ? "NO CLEAR WINNER"
    : budgetUnverified
      ? "BUDGET NOT COMPARABLE"
    : insufficientData
      ? "INSUFFICIENT DATA"
    : leader.verdict.toUpperCase() === "WORTH IT"
      ? "BUY THIS"
      : leader.verdict.toUpperCase() === "SKIP"
        ? "NEITHER"
        : "ANSME PICK";
  const priced = products.filter((product) => product.price !== null && isCurrencyCode(product.price_currency));
  const pricesComparable = priced.length === products.length
    && priced.length > 1
    && priced.every((product) => product.price_currency?.toUpperCase() === priced[0]?.price_currency?.toUpperCase());
  const cheapest = pricesComparable
    ? [...products].sort((a, b) => a.price! - b.price!)[0]
    : null;
  const priciest = pricesComparable
    ? [...products].sort((a, b) => b.price! - a.price!)[0]
    : null;
  const priceSpread = cheapest && priciest ? priciest.price! - cheapest.price! : null;
  const sharedCurrency = pricesComparable ? products[0]?.price_currency : null;
  const hasRequirements = request.requirements.trim().length > 0;
  const hasRatings = products.some((product) => product.rating !== null);
  const hasRequirementMatch = hasRequirements && products.some((product) => typeof product.analysis.requirement_match === "number");

  const breakdownAdvantage = selected
    ? Object.entries(selected.score_breakdown).map(([label, value]) => ({
        label: label.replace(" contribution", "").toLowerCase(),
        value,
        other: runnerUp.score_breakdown[label],
      })).filter((item): item is { label: string; value: number; other: number } =>
        typeof item.other === "number",
      )
      .sort((a, b) => (b.value - b.other) - (a.value - a.other))[0]
    : undefined;
  const tradeoff = selected && selected !== runnerUp
    ? hasRatings && runnerUp.rating !== null && selected.rating !== null && runnerUp.rating > selected.rating
      ? `The alternative has the higher published rating (${runnerUp.rating}/5 vs ${selected.rating}/5).`
      : pricesComparable && cheapest === runnerUp
        ? `The alternative costs less (${formatPrice(runnerUp.price, runnerUp.price_currency)}).`
        : hasRequirementMatch && runnerUp.analysis.requirement_match > selected.analysis.requirement_match
          ? `The alternative matches your stated requirements better (${runnerUp.analysis.requirement_match}/10 vs ${selected.analysis.requirement_match}/10).`
          : runnerUp.analysis.pros[0]
            ? `The alternative's available product details mention: ${runnerUp.analysis.pros[0]}.`
            : null
    : null;
  const selectedEvidence = selected?.evidence.find((item) => item.source.toLowerCase() === "strength");
  const selectedConcerns = selected?.evidence.find((item) => item.source.toLowerCase() === "concern");

  return <Screen name="comparison" scroll>
    <section className="glass-panel comparison-panel">
      <p className="eyebrow">Head-to-head decision</p>
      {products.find((product) => product.history_save_error)?.history_save_error
        && <p className="analysis-error" role="status">One or more analyses completed but could not be saved to your history.</p>}
      <div className={`comparison-verdict${undecided ? " undecided" : ""}`}>
        <div><span>{tied ? "The scores are tied" : budgetUnverified ? "The budget currency could not be matched to every price" : insufficientData ? "The scoring data is incomplete" : "Deterministic ANSME recommendation"}</span><h1>{banner}</h1></div>
        {selected && <p>{selected.title} · {selected.verdict} · {selected.overall_score.toFixed(1)}/10</p>}
        {tied
          ? <p>There is no clear score leader. Review the trade-offs below before choosing.</p>
          : budgetUnverified
            ? <p>The supplied budget affects the deterministic scores, but its currency is missing or does not match every product price. The score ranking is not a reliable buying recommendation.</p>
            : insufficientData && <p>The score leader has {leaderConfidenceLabel} confidence. ANSME cannot make a reliable pick from the available price and rating data.</p>}
      </div>

      <div className={`product-duel products-${products.length}`}>
        {products.map((product, index) => {
          const isSelected = selected === product;
          const confidence = confidencePercent(product);
          return <article className={`comparison-product${isSelected ? " is-selected" : ""}`} key={`${product.url}-${index}`} aria-label={isSelected ? "ANSME selected product" : undefined}>
            {isSelected && <span className="selected-label">ANSME PICK</span>}
            <div className="compare-image">
              {product.image_url
                ? <img src={product.image_url} alt={product.title} />
                : <div className="no-image"><Headphones /><span>No image provided</span></div>}
            </div>
            <h2>{product.title || product.url}</h2>
            <a className="product-source-link" href={product.url} target="_blank" rel="noopener noreferrer">View listing <ChevronRight /></a>
            <PriceValue product={product} />
            <div className="product-summary-stats">
              <div><span>Overall score</span><strong>{product.overall_score.toFixed(1)}<small>/10</small></strong></div>
              <div><span>Verdict</span><strong>{product.verdict}</strong></div>
              <div><span>Confidence</span><strong>{confidence === null ? "Unavailable" : `${confidence}%`}</strong></div>
            </div>
            {product.rating !== null && <p className="product-rating">Published rating <strong>{product.rating}/5</strong>{product.review_count !== null && ` · ${product.review_count.toLocaleString()} reviews`}</p>}
            <div className="compare-points">
              <Info title="Pros" items={product.analysis.pros} positive />
              <Info title="Cons" items={product.analysis.cons} />
            </div>
          </article>;
        })}
      </div>

      {scoreGap <= 0.1 && !tied && <p className="close-score-note">The top scores are very close ({scoreGap.toFixed(1)} point apart); treat this as a narrow lead, not a certainty.</p>}

      <section className="comparison-details">
        <h2>Side-by-side</h2>
        <div className="comparison-table-wrap">
          <table className="comparison-table">
            <thead><tr><th scope="col">Decision factor</th>{products.map((product, index) => <th scope="col" key={`${product.url}-head-${index}`}>{product.title || `Product ${index + 1}`}</th>)}</tr></thead>
            <tbody>
              <tr><th scope="row">Price</th>{products.map((product, index) => <td key={`${product.url}-price-${index}`}><PriceValue product={product} /></td>)}</tr>
              {hasRatings && <tr><th scope="row">Rating</th>{products.map((product, index) => <td key={`${product.url}-rating-${index}`}>{product.rating === null ? "Unavailable" : `${product.rating}/5${product.review_count === null ? "" : ` · ${product.review_count.toLocaleString()} reviews`}`}</td>)}</tr>}
              <tr><th scope="row">Evidence quality</th>{products.map((product, index) => {
                const evidenceQuality = product.evidence.length
                  ? product.evidence.reduce((total, item) => total + item.quality_score, 0) / product.evidence.length
                  : null;
                return <td key={`${product.url}-evidence-${index}`}>{evidenceQuality === null
                  ? "No evidence highlights"
                  : `${evidenceQuality.toFixed(0)}/100 average · ${product.evidence.length} extracted highlights from ${product.sources_analyzed} product page${product.sources_analyzed === 1 ? "" : "s"}`}</td>;
              })}</tr>
              {hasRequirementMatch && <tr><th scope="row">Requirements match</th>{products.map((product, index) => <td key={`${product.url}-requirements-${index}`}>{product.analysis.requirement_match}/10</td>)}</tr>}
            </tbody>
          </table>
        </div>
        {products.some((product) => product.price !== null) && (pricesComparable && cheapest && priciest && priceSpread !== null
          ? <p className="price-difference">Price spread: <strong>{formatPrice(priceSpread, sharedCurrency)}</strong>{priceSpread > 0 && priciest.price! > 0 && ` (${(priceSpread / priciest.price! * 100).toFixed(1)}% of the higher price)`}. Lowest listed: {cheapest.title || cheapest.url}.</p>
          : <p className="empty-state">Price differences are omitted because both prices and their currencies are not verified as comparable.</p>)}
      </section>

      <section className="winner">
        <Trophy aria-hidden="true" />
        <div>
          <small>{selected ? "WHY THIS PRODUCT LEADS" : "WHAT THE SCORES SAY"}</small>
          {selected
            ? <>
                <strong>{selected.title || selected.url} leads by {scoreGap.toFixed(1)} overall points.</strong>
                {breakdownAdvantage && breakdownAdvantage.value !== breakdownAdvantage.other && <p>The largest score contribution lead is {breakdownAdvantage.label}: {breakdownAdvantage.value.toFixed(2)} vs {breakdownAdvantage.other.toFixed(2)}. These are the scoring engine's weighted contributions.</p>}
                {selectedEvidence && <p>Available supporting evidence includes: “{selectedEvidence.snippet}”</p>}
                {selectedConcerns && <p>Trade-off to consider: “{selectedConcerns.snippet}”</p>}
                {tradeoff && <p>Alternative to weigh: {tradeoff}</p>}
              </>
            : tied
              ? <strong>Both products have the same overall score ({leader.overall_score.toFixed(1)}/10). No winner is claimed.</strong>
              : budgetUnverified
                ? <strong>The score ranking cannot be trusted as a buying recommendation until the budget and all listed prices are confirmed in the same currency.</strong>
                : <strong>{leader.title || leader.url} has the highest score, but its available confidence data is too limited to recommend it.</strong>}
        </div>
      </section>
      <Link className="action-button primary-action" to="/workspace">Analyze another</Link>
    </section>
  </Screen>;
}
export function HistoryScreen() {
  const navigate = useNavigate();
  const { history, setHistory, setResult } = useAnsme();
  const [search, setSearch] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [historyLoading, setHistoryLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function loadHistory() {
      try {
        const data = await getAllHistory();

        if (!cancelled) {
          setHistory(data.map(mapHistoryRecord));
        }
      } catch (err) {
        console.error(err);

        if (!cancelled) {
          setError("Unable to load analysis history.");
        }
      } finally {
        if (!cancelled) setHistoryLoading(false);
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

  function exportHistoryCsv() {
    const rows = [
      ["title", "price", "score", "verdict", "date"],
      ...history.map((item) => [
        item.title,
        item.price,
        item.score.toFixed(1),
        item.verdict,
        item.date,
      ]),
    ];
    const csv = rows
      .map((row) => row.map((value) => `"${value.replaceAll('"', '""')}"`).join(","))
      .join("\r\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const downloadUrl = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = downloadUrl;
    anchor.download = "ansme-history.csv";
    anchor.click();
    URL.revokeObjectURL(downloadUrl);
  }

  async function reopenAnalysis(id: string) {
    try {
      const analysis = await getHistoryItem(Number(id));

      setResult({
        status: "success",
        url: analysis.url,
        title: analysis.title ?? analysis.url,
        brand: analysis.brand,
        price: analysis.price,
        ...(analysis.price_raw !== undefined ? { price_raw: analysis.price_raw } : {}),
        ...(analysis.price_currency !== undefined ? { price_currency: analysis.price_currency } : {}),
        rating: analysis.rating,
        image_url: analysis.image_url,
        description: analysis.description,
        overall_score: analysis.overall_score,
        verdict: analysis.verdict,
        metrics: analysis.metrics ?? {},
        score_breakdown: analysis.score_breakdown ?? {},
        processing_time_ms: analysis.processing_time_ms ?? 0,
        sources_analyzed: analysis.sources_analyzed ?? 0,
        evidence: analysis.evidence ?? [],
        category: analysis.category,
        review_count: analysis.review_count,
        price_history: analysis.price_history,
        similar_products: analysis.similar_products,
        analysis: {
          sentiment_score: analysis.sentiment_score ?? 0,
          requirement_match: analysis.requirement_match ?? 0,
          pros: analysis.pros ?? [],
          cons: analysis.cons ?? [],
          risk_flags: analysis.risk_flags ?? [],
          explanation: analysis.explanation ?? "",
        },
      });

      navigate({ to: "/result" });
    } catch (err) {
      console.error(err);
      setError("Unable to reopen this analysis.");
    }
  }

  const normalizedSearch = search.trim().toLowerCase();
  const filtered = history.filter((item) =>
    [item.title, item.url, item.price, item.verdict, item.date]
      .some((value) => value.toLowerCase().includes(normalizedSearch))
  );
  return <Screen name="history" scroll><section className="glass-panel history-panel"><p className="eyebrow">Decision archive</p><h1>Your past calls</h1><label className="search-box"><Search /><input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search analyses" /></label><button type="button" className="action-button" onClick={exportHistoryCsv} disabled={historyLoading}><Download />Export CSV</button>{error && <p className="analysis-error" role="alert">{error}</p>}<div className="history-list">{historyLoading ? <p role="status">Loading analysis history…</p> : error ? null : filtered.length ? filtered.map((item) => <article key={item.id}><div><small><Clock3 />{item.date}</small><h2>{item.title}</h2><p>{item.price} · Score {item.score.toFixed(1)}</p></div><div><span className={`verdict-badge ${item.verdict.toLowerCase().replace(" ", "-")}`}>{item.verdict}</span><button type="button" onClick={() => void reopenAnalysis(item.id)}>Reopen <ChevronRight /></button><button type="button" className="icon-button" aria-label={`Delete ${item.title}`} onClick={() => void handleDelete(item.id)}><Trash2 /></button></div></article>) : <p>{search ? "No analyses match your search." : "No saved analyses yet."}</p>}</div><Link to="/workspace" className="action-button primary-action"><Plus />New analysis</Link></section></Screen>;
}

export function LeaderboardScreen() {
  const [leaderboard, setLeaderboard] = useState<{
    highest: LeaderboardItem[];
    lowest: LeaderboardItem[];
  } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getLeaderboard()
      .then((data) => {
        if (!cancelled) setLeaderboard(data);
      })
      .catch((err: unknown) => {
        console.error(err);
        if (!cancelled) setError("Unable to load the product leaderboard.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function renderEntries(title: string, entries: LeaderboardItem[]) {
    return <section className="leaderboard-list"><h2>{title}</h2>{entries.length ? entries.map((item, index) => <article key={`${item.title}-${index}`}><span>#{index + 1}</span><div>{item.url ? <a href={item.url} target="_blank" rel="noopener noreferrer">{item.title}</a> : <span>{item.title}</span>}<small>{item.category} · {item.verdict}</small></div><strong>{item.overall_score.toFixed(1)}/10</strong></article>) : <p>No analyzed products yet.</p>}</section>;
  }

  return <Screen name="workspace" scroll><section className="glass-panel leaderboard-panel"><p className="eyebrow">Community data</p><h1>Product leaderboard</h1>{error && <p className="analysis-error" role="alert">{error}</p>}{leaderboard && <>{renderEntries("Top 10 highest scoring", leaderboard.highest)}{renderEntries("Top 10 lowest scoring", leaderboard.lowest)}</>}</section></Screen>;
}

function mapHistoryRecord(item: HistoryRecord): HistoryItem {
  return {
    id: String(item.id),
    title: item.title ?? item.url,
    url: item.url,
    date: new Date(item.created_at).toLocaleDateString(),
    verdict: item.verdict,
    price: formatPrice(item.price, item.price_currency, item.price_raw),
    score: item.overall_score,
  };
}
const legal = { privacy: { title: "Privacy", body: "Your product links and preferences are used only to create your analysis. You control whether analysis history is saved." }, terms: { title: "Terms", body: "ANSME provides research-based guidance, not a guarantee. Prices, availability, and product details may change." }, disclaimer: { title: "Disclaimer", body: "Verdicts are informational and should be one input in your decision. Always review current seller terms and safety guidance." } };
export function SettingsScreen() {
  const { settings, setSettings, setHistory } = useAnsme();
  const [tab, setTab] = useState<"settings" | keyof typeof legal>("settings");
  const [dataActionError, setDataActionError] = useState<string | null>(null);
  const [dataActionStatus, setDataActionStatus] = useState<string | null>(null);
  const [dataActionProgress, setDataActionProgress] = useState<string | null>(null);
  const [dataActionInProgress, setDataActionInProgress] = useState(false);
  const [leaderboardPreferenceLoading, setLeaderboardPreferenceLoading] = useState(true);
  const [leaderboardPreferenceLoaded, setLeaderboardPreferenceLoaded] = useState(false);
  const [leaderboardPreferenceSaving, setLeaderboardPreferenceSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getLeaderboardParticipation()
      .then((enabled) => {
        if (!cancelled) {
          setSettings((current) => ({ ...current, shareToLeaderboard: enabled }));
          setLeaderboardPreferenceLoaded(true);
        }
      })
      .catch((error: unknown) => {
        console.error("Unable to load leaderboard participation preference.", error);
        if (!cancelled) {
          setDataActionError("Unable to load your leaderboard sharing preference.");
        }
      })
      .finally(() => {
        if (!cancelled) setLeaderboardPreferenceLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [setSettings]);

  async function handleLeaderboardParticipationChange(enabled: boolean) {
    setLeaderboardPreferenceSaving(true);
    setDataActionError(null);
    setDataActionStatus(null);
    try {
      await setLeaderboardParticipation(enabled);
      setSettings({ ...settings, shareToLeaderboard: enabled });
      setLeaderboardPreferenceLoaded(true);
      setDataActionStatus(
        enabled
          ? "Your saved analyses are now included in the community leaderboard."
          : "Your saved analyses have been removed from the community leaderboard.",
      );
    } catch (error) {
      console.error("Unable to update leaderboard participation.", error);
      setDataActionError("Unable to update your leaderboard sharing preference.");
    } finally {
      setLeaderboardPreferenceSaving(false);
    }
  }

  async function handleExportData() {
    setDataActionInProgress(true);
    setDataActionError(null);
    setDataActionStatus(null);

    try {
      const records = await getAllHistory();
      const analyses: Awaited<ReturnType<typeof getHistoryItem>>[] = [];
      for (let index = 0; index < records.length; index += 10) {
        const page = records.slice(index, index + 10);
        analyses.push(
          ...(await Promise.all(page.map((record) => getHistoryItem(record.id)))),
        );
      }
      const blob = new Blob([JSON.stringify(analyses, null, 2)], {
        type: "application/json",
      });
      const downloadUrl = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = downloadUrl;
      anchor.download = "ansme-analysis-history.json";
      anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(downloadUrl), 1_000);
      setDataActionStatus(`Exported ${analyses.length} saved analyses.`);
    } catch (error) {
      console.error("Unable to export analysis history.", error);
      setDataActionError("Unable to export analysis history. Please try again.");
    } finally {
      setDataActionInProgress(false);
    }
  }

  async function handleDeleteData() {
    setDataActionInProgress(true);
    setDataActionError(null);
    setDataActionStatus(null);

    try {
      const records = await getAllHistory();
      if (records.length === 0) {
        setDataActionStatus("There are no saved analyses to delete.");
        return;
      }

      const confirmed = window.confirm(
        `Permanently delete all ${records.length} saved analyses? This cannot be undone.`,
      );
      if (!confirmed) return;

      const { deletedIds, failures } = await deleteHistoryRecords(
        records,
        (id) => deleteHistoryItem(id),
        (index, total) => {
          setDataActionProgress(`Deleting analysis ${index} of ${total}…`);
        },
      );
      for (const failure of failures) {
        console.error(`Unable to delete analysis ${failure.id}.`, failure.error);
      }

      const deletedIdSet = new Set(deletedIds.map(String));
      setHistory((current) =>
        current.filter((record) => !deletedIdSet.has(record.id)),
      );

      if (failures.length > 0) {
        setDataActionError(
          `Deleted ${deletedIds.length} analyses, but ${failures.length} could not be deleted. Please retry.`,
        );
      } else {
        setDataActionStatus(`Deleted all ${deletedIds.length} saved analyses.`);
      }
    } catch (error) {
      console.error("Unable to delete analysis history.", error);
      setDataActionError(
        "Unable to load analysis history for deletion. No analyses were deleted.",
      );
    } finally {
      setDataActionInProgress(false);
      setDataActionProgress(null);
    }
  }

  return <Screen name="settings" scroll><section className="glass-panel settings-panel"><div className="tabs">{(["settings", "privacy", "terms", "disclaimer"] as const).map((name) => <button key={name} className={tab === name ? "active" : ""} onClick={() => setTab(name)}>{name}</button>)}</div>{tab === "settings" ? <><p className="eyebrow">Your rules</p><h1>Settings</h1><div className="setting-list"><Toggle label="Save analysis history" value={settings.saveHistory} onChange={(value) => setSettings({ ...settings, saveHistory: value })} /><Toggle label="Personalized advice" value={settings.personalizedAdvice} onChange={(value) => setSettings({ ...settings, personalizedAdvice: value })} /><Toggle label="Notifications" value={settings.notifications} onChange={(value) => setSettings({ ...settings, notifications: value })} icon={<Bell />} /><Toggle label="Share analyses on community leaderboard" value={settings.shareToLeaderboard} onChange={(value) => void handleLeaderboardParticipationChange(value)} disabled={leaderboardPreferenceLoading || leaderboardPreferenceSaving || !leaderboardPreferenceLoaded} /><label className="theme-row"><span>Theme preference</span><select value={settings.theme} onChange={(e) => setSettings({ ...settings, theme: e.target.value as UserSettings["theme"] })}><option value="dark">Dark</option><option value="light">Light</option><option value="system">Use device setting</option></select></label></div><p className="empty-state">Sharing is off by default. When enabled, product title, a sanitized product link (without credentials, query parameters, or fragments), score, verdict, and category for your saved analyses are public. Unsafe or unsupported links are omitted. No account identifiers are shared. Deleting analysis history does not delete your Supabase account.</p><div className="data-actions"><button type="button" onClick={() => void handleExportData()} disabled={dataActionInProgress}><Download />{dataActionInProgress ? "Working…" : "Export data"}</button><button type="button" className="danger-action" onClick={() => void handleDeleteData()} disabled={dataActionInProgress}><Trash2 />Delete analysis history</button></div>{dataActionProgress && <p role="status">{dataActionProgress}</p>}{dataActionError && <p className="analysis-error" role="alert">{dataActionError}</p>}{dataActionStatus && <p role="status">{dataActionStatus}</p>}<p className="privacy-note"><ShieldCheck />Your data, your call.</p></> : <motion.div key={tab} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="legal-copy"><p className="eyebrow">ANSME</p><h1>{legal[tab].title}</h1><p>{legal[tab].body}</p><p>We keep our language clear, collect only what the experience needs, and never sell personal information.</p></motion.div>}</section></Screen>;
}
function Toggle({ label, value, onChange, icon, disabled = false }: { label: string; value: boolean; onChange: (value: boolean) => void; icon?: ReactNode; disabled?: boolean }) { return <label className="toggle-row"><span>{icon}{label}</span><button type="button" role="switch" aria-checked={value} aria-label={label} className={value ? "on" : ""} disabled={disabled} onClick={() => onChange(!value)}><span /></button></label>; }
