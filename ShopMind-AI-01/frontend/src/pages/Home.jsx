import React from "react";
import {
  ArrowRight, BarChart3, Clock3, GitCompare, Heart, Link2, MapPin,
  PackageCheck, Search, ShieldCheck, ShoppingBag, Sparkles, TrendingDown,
  Zap, Laptop, Shirt, Home as HomeIcon, Refrigerator, Coffee, Smartphone,
  ChevronRight, LocateFixed, CheckCircle2
} from "lucide-react";
import SearchBox from "../components/SearchBox";

const categories = [
  { title: "Groceries", icon: ShoppingBag, query: "groceries under ₹1000", accent: "mint" },
  { title: "Electronics", icon: Smartphone, query: "best electronics deals under ₹5000", accent: "blue" },
  { title: "Laptops", icon: Laptop, query: "best laptop for coding under ₹60000", accent: "violet" },
  { title: "Fashion", icon: Shirt, query: "best fashion deals under ₹3000", accent: "pink" },
  { title: "Home", icon: HomeIcon, query: "best home products under ₹3000", accent: "cyan" },
  { title: "Appliances", icon: Refrigerator, query: "best appliances deals under ₹10000", accent: "orange" },
  { title: "Beauty", icon: Sparkles, query: "best beauty products under ₹2000", accent: "purple" },
  { title: "Daily Needs", icon: Coffee, query: "daily essentials near me", accent: "green" },
];

const missions = [
  { icon: TrendingDown, title: "Find the lowest price", text: "Compare trusted stores", query: "lowest price deals under ₹5000" },
  { icon: Zap, title: "Get it fast", text: "10–30 min quick-commerce", query: "instant delivery everyday essentials" },
  { icon: BarChart3, title: "Buy at the right time", text: "Check price history", query: "products with good price history under ₹5000" },
];

export default function Home({
  onSearch, loading, liveLocation, locationContext,
  locationStatus = "unavailable", onRequestLocation,
}) {
  const [pincode, setPincode] = React.useState("");
  const displayRegion = locationContext?.label || (liveLocation ? "Nearby region detected" : "Set your location");
  const isIndia = locationContext?.country_code === "IN";

  const runInstant = () => {
    if (pincode.length !== 6) return;
    onSearch?.("instant delivery for everyday products", { postal_code: pincode });
  };

  return (
    <main className="v18-home">
      <div className="v18-noise" />
      <div className="v18-orb v18-orb-one" />
      <div className="v18-orb v18-orb-two" />

      <section className="v18-hero">
        <div className="v18-hero-copy">
          <div className="v18-kicker"><Sparkles size={14} /> AI-POWERED SHOPPING AGENT <span /></div>
          <h1>Shop smarter.<br /><em>Buy better.</em></h1>
          <p>Tell ShopMind what you want. We compare trusted stores, prices, delivery speeds and buying signals — then help you choose.</p>
          <div className="v18-hero-points">
            <span><CheckCircle2 size={14}/> Multi-store comparison</span>
            <span><CheckCircle2 size={14}/> Price intelligence</span>
            <span><CheckCircle2 size={14}/> Location-aware delivery</span>
          </div>
        </div>

        <div className="v18-hero-workspace">
          <div className="v18-search-glass">
            <SearchBox onSearch={onSearch} loading={loading} postalCode={pincode} />
          </div>
          <aside className="v18-ai-card">
            <div className="v18-ai-head"><span><span className="pulse"/> LIVE</span><b>ShopMind Intelligence</b><Sparkles size={16}/></div>
            <div className="v18-score-row"><div><small>BUY SCORE</small><strong>94</strong><span>/100</span></div><div className="v18-score-ring">A+</div></div>
            <div className="v18-chart"><i/><i/><i/><i/><i/><i/><i/></div>
            <div className="v18-price"><div><small>Best current offer</small><strong>₹1,249</strong></div><span><TrendingDown size={13}/> 12% lower</span></div>
            <div className="v18-ai-meta"><span><ShieldCheck size={13}/> Verified sources</span><span><Clock3 size={13}/> 18 min nearby</span></div>
          </aside>
        </div>
      </section>

      <section className="v18-location-bar">
        <div className="v18-location-main"><div className="location-icon"><MapPin size={17}/></div><div><small>DELIVER TO</small><strong>{displayRegion}</strong></div></div>
        <div className="v18-location-status">{locationStatus === "ready" ? <><span className="pulse"/> Location ready</> : <>Set location for better delivery matches</>}</div>
        <button onClick={onRequestLocation} disabled={locationStatus === "detecting"}><LocateFixed size={15}/>{locationStatus === "detecting" ? "Detecting…" : "Use live location"}</button>
        {isIndia && <div className="v18-pin-wrap"><MapPin size={14}/><input value={pincode} onChange={e => setPincode(e.target.value.replace(/\D/g, "").slice(0,6))} maxLength={6} placeholder="Pincode"/><button disabled={pincode.length !== 6 || loading} onClick={runInstant}>Apply</button></div>}
      </section>

      <section className="v18-section">
        <div className="v18-section-head"><div><span className="v18-eyebrow">DISCOVER</span><h2>What are you shopping for?</h2><p>Start with a category or just describe what you need.</p></div><button className="v18-ghost" onClick={() => onSearch?.("best deals today")}>View all deals <ArrowRight size={15}/></button></div>
        <div className="v18-category-grid">
          {categories.map(({title, icon: Icon, query, accent}) => <button key={title} className={`v18-category ${accent}`} onClick={() => onSearch?.(query)}><span className="v18-category-icon"><Icon size={22}/></span><span><b>{title}</b><small>Explore deals</small></span><ChevronRight size={15}/></button>)}
        </div>
      </section>

      <section className="v18-instant">
        <div className="v18-instant-head"><div><span className="v18-eyebrow"><Zap size={13}/> QUICK COMMERCE</span><h2>Need it in 10–30 minutes?</h2><p>Use your location and pincode to prioritize nearby instant-delivery sources. Exact ETA depends on item, stock and local availability.</p></div><button className="v18-outline" onClick={() => onSearch?.("instant delivery for everyday products", pincode ? {postal_code:pincode} : {})}>Explore instant <ArrowRight size={15}/></button></div>
        <div className="v18-source-grid">
          {["Blinkit","Zepto","Swiggy Instamart","bbnow","Flipkart Minutes"].map((name, i) => <button key={name} className="v18-source" onClick={() => onSearch?.(`instant delivery from ${name} for everyday products`, pincode ? {postal_code:pincode} : {})}><span className={`source-mark s${i}`}>{name[0]}</span><div><b>{name}</b><small>{i === 3 ? "10–20 min" : i === 4 ? "~10 min" : "10–30 min"}</small></div><ChevronRight size={14}/></button>)}
        </div>
      </section>

      <section className="v18-missions">
        <div className="v18-section-head"><div><span className="v18-eyebrow">SMART MISSIONS</span><h2>What matters most?</h2></div></div>
        <div className="v18-mission-grid">{missions.map(({icon:Icon,title,text,query}) => <button key={title} className="v18-mission" onClick={() => onSearch?.(query)}><span><Icon size={20}/></span><div><b>{title}</b><small>{text}</small></div><ArrowRight size={15}/></button>)}</div>
      </section>

      <section className="v18-how">
        <div className="v18-how-title"><span className="v18-eyebrow">HOW IT WORKS</span><h2>Your personal AI shopping agent</h2><p>From a simple request to a confident purchase decision.</p></div>
        <div className="v18-steps"><div><span>01</span><ShoppingBag size={22}/><h3>Tell us what you need</h3><p>Natural language, product link or quick-commerce request.</p></div><div><span>02</span><GitCompare size={22}/><h3>We compare</h3><p>Merchants, prices, reviews, delivery and buying signals.</p></div><div><span>03</span><Heart size={22}/><h3>Buy with confidence</h3><p>Choose the best overall, cheapest or fastest option.</p></div></div>
      </section>
    </main>
  );
}
