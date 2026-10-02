import React, { useMemo, useState } from "react";
import { ArrowRight, Link2, Search, Sparkles, Zap } from "lucide-react";

const MODES = [
    { id: "shop", label: "AI Shop", icon: Sparkles },
    { id: "compare", label: "Compare", icon: Search },
    { id: "instant", label: "Instant Delivery", icon: Zap },
    { id: "link", label: "Paste Product Link", icon: Link2 },
];

export default function SearchBox({ onSearch, loading = false, initialValue = "", postalCode = "" }) {
    const [query, setQuery] = useState(initialValue);
    const [mode, setMode] = useState("shop");

    const placeholder = useMemo(() => {
        if (mode === "instant") return "e.g. rice 5kg under ₹500, deliver in 30 minutes";
        if (mode === "compare") return "e.g. iPhone 17 256GB — compare every store";
        if (mode === "link") return "Paste an Amazon / Flipkart / Myntra product URL";
        return "Tell me what you want to buy...";
    }, [mode]);

    function submit(event) {
        event.preventDefault();
        const value = query.trim();
        if (!value || loading) return;

        let finalQuery = value;
        if (mode === "instant") finalQuery = `instant delivery: ${value}`;
        if (mode === "compare") finalQuery = `compare prices: ${value}`;
        if (mode === "link") finalQuery = `find the best price and compare offers for this product link: ${value}`;
        onSearch(finalQuery, mode === "instant" && /^\d{6}$/.test(postalCode) ? { postal_code: postalCode } : {});
    }

    const suggestions = [
        { label: "Wireless earbuds under ₹1500 with ANC", mode: "shop" },
        { label: "Best laptop under ₹60000 for coding", mode: "compare" },
        { label: "26 kg rice delivered today", mode: "instant" },
    ];

    return (
        <div className="search-area">
            <div className="search-mode-tabs" role="tablist" aria-label="Shopping mode">
                {MODES.map(({ id, label, icon: Icon }) => (
                    <button
                        key={id}
                        type="button"
                        className={mode === id ? "search-mode active" : "search-mode"}
                        onClick={() => setMode(id)}
                        disabled={loading}
                    >
                        <Icon size={14} /> {label}
                    </button>
                ))}
            </div>

            <div className="ai-provider-bar automatic-provider">
                <span className="ai-provider-label"><Sparkles size={13} /> AI engine</span>
                <span className="auto-provider-pill">Auto · Best available</span>
                <span className="search-trust-copy">Prices, availability and ETAs stay source-dependent.</span>
            </div>

            <form className="search-form" onSubmit={submit}>
                <div className="search-icon"><Search size={22} /></div>
                <input
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder={placeholder}
                    disabled={loading}
                    aria-label="Shopping query"
                />
                <button type="submit" disabled={loading || !query.trim()} className="search-button">
                    {loading ? <><span className="spinner" /> Searching</> : <>Search <ArrowRight size={17} /></>}
                </button>
            </form>

            <div className="suggestions">
                <span><Sparkles size={14} /> Try:</span>
                {suggestions.map((item) => (
                    <button key={item.label} type="button" onClick={() => {
                        setMode(item.mode);
                        setQuery(item.label);
                        let finalQuery = item.label;
                        if (item.mode === "instant") finalQuery = `instant delivery: ${item.label}`;
                        if (item.mode === "compare") finalQuery = `compare prices: ${item.label}`;
                        onSearch?.(finalQuery, item.mode === "instant" && /^\d{6}$/.test(postalCode) ? { postal_code: postalCode } : {});
                    }} disabled={loading}>{item.label}</button>
                ))}
            </div>
            <div className="search-assurance-row">
                <span><Zap size={13} /> Instant mode uses your location + pincode</span>
                <span><Sparkles size={13} /> Natural language supported</span>
                <span><Link2 size={13} /> Product links accepted</span>
            </div>
        </div>
    );
}
