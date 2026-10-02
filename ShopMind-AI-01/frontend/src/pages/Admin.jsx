import React, { useState } from "react";
import { BarChart3, Shield } from "lucide-react";

export default function Admin() {
  const [key, setKey] = useState("");
  const [stats, setStats] = useState(null);
  const [error, setError] = useState("");
  async function load() {
    setError("");
    try {
      const r = await fetch("/api/v1/admin/stats", { headers: { "X-Admin-Key": key } });
      if (!r.ok) throw new Error((await r.json()).detail || "Unauthorized");
      setStats(await r.json());
    } catch (e) { setError(e.message); }
  }
  return <main className="results-page"><section className="query-summary"><span className="eyebrow"><Shield size={14}/> ADMIN</span><h1>ShopMind Analytics</h1><p>Operational statistics. Admin key is sent only to the backend.</p><div className="admin-key-row"><input type="password" value={key} onChange={e=>setKey(e.target.value)} placeholder="Admin API key"/><button className="primary-button" onClick={load}><BarChart3 size={16}/> Load stats</button></div></section>{error&&<div className="inline-error">{error}</div>}{stats&&<div className="home-intelligence-strip"><div><strong>{stats.searches}</strong><span>Searches</span></div><div><strong>{stats.products_recorded}</strong><span>Products recorded</span></div><div><strong>{stats.wishlist_items}</strong><span>Wishlist items</span></div><div><strong>{stats.active_alerts}</strong><span>Active alerts</span></div></div>}</main>;
}
