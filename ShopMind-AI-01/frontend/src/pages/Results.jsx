import React, { useEffect, useMemo, useState } from "react";
import {
    ArrowLeft,
    SlidersHorizontal,
    LayoutGrid,
    List,
    GitCompareArrows,
    X,
    MapPin,
    Zap,
    Sparkle,
    RefreshCw,
    AlertCircle,
    Store,
    PackageSearch,
    Sparkles,
    CheckCircle2,
    XCircle,
    ShieldCheck,
    BellRing,
    Clock3,
    TrendingDown,
} from "lucide-react";

import ProductCard from "../components/ProductCard";
import ComparisonTable from "../components/ComparisonTable";
import RecommendationCard from "../components/RecommendationCard";

function flattenSearchResults(searchResults) {
    const all = [];

    if (!searchResults || typeof searchResults !== "object") {
        return all;
    }

    for (const [merchantId, products] of Object.entries(searchResults)) {
        if (!Array.isArray(products)) continue;

        for (const product of products) {
            if (!product || typeof product !== "object") continue;

            // Keep the merchant id even when an older backend response
            // omits it from the product payload.
            all.push({
                ...product,
                merchant_id: product.merchant_id || merchantId,
            });
        }
    }

    return all;
}

function uniqueProducts(products) {
    const unique = new Map();

    for (const product of products) {
        const key =
            `${product.merchant_id || "merchant"}:` +
            `${product.product_id || product.id || product.name}`;

        if (!unique.has(key)) {
            unique.set(key, product);
        }
    }

    return [...unique.values()];
}

function sortProducts(products, mode = "price_low") {
    return [...products].sort((a, b) => {
        const priceA = Number(a.display_price ?? a.price);
        const priceB = Number(b.display_price ?? b.price);
        const safeA = Number.isFinite(priceA) && priceA > 0 ? priceA : Infinity;
        const safeB = Number.isFinite(priceB) && priceB > 0 ? priceB : Infinity;

        if (mode === "price_high") return safeB - safeA;
        if (mode === "rating") {
            const ratingDiff = Number(b.rating || 0) - Number(a.rating || 0);
            if (ratingDiff !== 0) return ratingDiff;
            return safeA - safeB;
        }
        if (mode === "reviews") {
            const reviewDiff = Number(b.review_count || 0) - Number(a.review_count || 0);
            if (reviewDiff !== 0) return reviewDiff;
            return safeA - safeB;
        }
        if (mode === "best") {
            const scoreDiff = Number(b.score || 0) - Number(a.score || 0);
            if (scoreDiff !== 0) return scoreDiff;
            return safeA - safeB;
        }
        return safeA - safeB;
    });
}

export default function Results({
    sessionId,
    session,
    loading,
    error,
    onBack,
    onRefresh,
    onSelectProduct,
    onConfirm,
    onCancel,
}) {
    const [selectedProduct, setSelectedProduct] = useState(null);
    const [sortMode, setSortMode] = useState("price_low");
    const [minRating, setMinRating] = useState(0);
    const [instantOnly, setInstantOnly] = useState(false);
    const [verifiedOnly, setVerifiedOnly] = useState(false);
    const [feature, setFeature] = useState("");
    const [viewMode, setViewMode] = useState("grid");
    const [filterOpen, setFilterOpen] = useState(false);
    const [compareItems, setCompareItems] = useState([]);

    const entries = session?.comparison?.entries || [];

    // IMPORTANT FIX:
    // The old UI only read comparison.entries. If comparison was empty
    // but search_results already contained products, the UI incorrectly
    // displayed "No matching products found".
    const searchProducts = useMemo(
        () => flattenSearchResults(session?.search_results),
        [session?.search_results]
    );

    const comparisonProducts = useMemo(() => {
        const all = [];

        for (const entry of entries) {
            for (const product of entry.merchant_results || []) {
                all.push(product);
            }
        }

        return all;
    }, [entries]);

    const products = useMemo(() => {
        const source =
            comparisonProducts.length > 0
                ? comparisonProducts
                : searchProducts;

        let filtered = uniqueProducts(source);
        if (minRating > 0) filtered = filtered.filter((p) => Number(p.rating || 0) >= minRating);
        if (instantOnly) filtered = filtered.filter((p) => {
            const eta = Number(p.eta_minutes);
            return Number.isFinite(eta) ? eta <= 30 : Boolean(p.specs?.delivery_window);
        });
        if (verifiedOnly) filtered = filtered.filter((p) => p.verified_source !== false);
        if (feature.trim()) {
            const needle = feature.toLowerCase();
            filtered = filtered.filter((p) => JSON.stringify(p).toLowerCase().includes(needle));
        }
        return sortProducts(filtered, sortMode);
    }, [comparisonProducts, searchProducts, sortMode, minRating, instantOnly, verifiedOnly, feature]);

    const recommended =
        entries.find((entry) => entry?.recommended)?.recommended ||
        entries[0]?.recommended ||
        products[0] ||
        null;

    useEffect(() => {
        if (recommended) {
            setSelectedProduct(recommended);
        }
    }, [recommended]);

    function selectProduct(product) {
        setSelectedProduct(product);
        onSelectProduct?.(product);
    }

    function toggleCompare(product) {
        setCompareItems((current) => {
            const key = `${product.merchant_id || "merchant"}:${product.product_id || product.id || product.name}`;
            const exists = current.some((item) => `${item.merchant_id || "merchant"}:${item.product_id || item.id || item.name}` === key);
            if (exists) return current.filter((item) => `${item.merchant_id || "merchant"}:${item.product_id || item.id || item.name}` !== key);
            if (current.length >= 3) return current;
            return [...current, product];
        });
    }

    if (error && !session) {
        return (
            <main className="results-page">
                <div className="error-card">
                    <AlertCircle size={35} />
                    <h2>Something went wrong</h2>
                    <p>{error}</p>
                    <button className="primary-button" onClick={onBack}>
                        Go Back
                    </button>
                </div>
            </main>
        );
    }

    const merchantCount =
        session?.merchants?.length ||
        Object.keys(session?.search_results || {}).length ||
        0;

    const productCount =
        session?.comparison?.total_products_found ||
        searchProducts.length ||
        products.length;

    const optimization = session?.optimization_plan;

    return (
        <main className="results-page">
            <div className="results-toolbar">
                <button className="back-button" onClick={onBack}>
                    <ArrowLeft size={17} />
                    New Search
                </button>

                <div className="session-info">
                    <span>Session</span>
                    <code>{sessionId?.slice(0, 8) || "—"}</code>

                    <button
                        className="refresh-button"
                        onClick={onRefresh}
                        disabled={loading}
                        title="Refresh results"
                    >
                        <RefreshCw
                            size={15}
                            className={loading ? "spin" : ""}
                        />
                    </button>
                </div>
            </div>

            {loading && (
                <div className="processing-banner">
                    <Sparkles size={15} />
                    ShopMind AI is still working on your request...
                </div>
            )}

            {error && (
                <div className="inline-error">
                    <AlertCircle size={16} />
                    {error}
                </div>
            )}

            {session?.state === "awaiting_confirmation" && (
                <section className="confirmation-card">
                    <div className="confirmation-copy">
                        <div className="confirmation-icon"><ShieldCheck size={22} /></div>
                        <div>
                            <span className="eyebrow">HUMAN CONFIRMATION REQUIRED</span>
                            <h2>Review before checkout</h2>
                            <p>ShopMind has prepared the best available purchase plan. No order will be placed until you confirm it.</p>
                        </div>
                    </div>
                    <div className="confirmation-actions">
                        <button className="secondary-button" onClick={onCancel} disabled={loading}>
                            <XCircle size={16} /> Cancel
                        </button>
                        <button className="primary-button" onClick={onConfirm} disabled={loading}>
                            <CheckCircle2 size={16} /> Confirm & Checkout
                        </button>
                    </div>
                </section>
            )}

            {session?.request && (
                <section className="query-summary">
                    <div className="query-summary-top">
                        <div>
                            <span>Your request</span>
                            <h1>{session.request.query}</h1>
                        </div>

                        <div className="status-pill">
                            <span className="status-dot online" />
                            {String(session.state || "processing").replaceAll(
                                "_",
                                " "
                            )}
                        </div>
                    </div>

                    <div className="query-stats">
                        <span>
                            <Store size={14} />
                            {merchantCount} sources
                        </span>

                        {session?.request?.country_code && (
                            <span>
                                🌍 {session.request.country_code}
                                {" · "}
                                {session.request.display_currency || "USD"}
                            </span>
                        )}

                        <span>
                            <PackageSearch size={14} />
                            {productCount} products
                        </span>

                        {optimization?.grand_total != null && (
                            <span>
                                Total:{" "}
                                <strong>
                                    {formatMoney(
                                        optimization.grand_total,
                                        optimization.display_currency || optimization.items?.[0]?.currency
                                    )}
                                </strong>
                            </span>
                        )}
                    </div>
                </section>
            )}

            {recommended && <RecommendationCard product={recommended} />}

            <section className="results-intelligence-grid">
                <InsightCard icon={<TrendingDown size={17} />} label="Best current value" value={recommended ? `${formatMoney(recommended.display_price ?? recommended.price, recommended.display_currency || recommended.currency)}` : "Waiting"} note={recommended?.price_signal?.signal?.replaceAll("_", " ") || "AI ranking in progress"} />
                <InsightCard icon={<Clock3 size={17} />} label="Instant options" value={`${products.filter((p) => p.eta_minutes || p.specs?.delivery_window).length}`} note="Quick-commerce matches" />
                <InsightCard icon={<ShieldCheck size={17} />} label="Verified offers" value={`${products.filter((p) => p.verified_source !== false).length}`} note="Source-aware ranking" />
                <InsightCard icon={<BellRing size={17} />} label="Price watch" value="Ready" note="Set alerts from any card" />
            </section>

            <section className="results-command-bar">
                <div className="result-mode-copy">
                    <div className="eyebrow"><Sparkle size={13} /> AI SHOPPING RESULTS</div>
                    <strong>{products.length} offers found</strong>
                    <span>Ranked for price, trust, delivery and fit.</span>
                </div>
                <div className="result-command-actions">
                    <button className={`filter-toggle ${filterOpen ? "active" : ""}`} onClick={() => setFilterOpen((v) => !v)}><SlidersHorizontal size={15}/> Filters</button>
                    <div className="view-toggle" aria-label="View mode">
                        <button className={viewMode === "grid" ? "active" : ""} onClick={() => setViewMode("grid")}><LayoutGrid size={15}/></button>
                        <button className={viewMode === "list" ? "active" : ""} onClick={() => setViewMode("list")}><List size={15}/></button>
                    </div>
                </div>
            </section>

            {filterOpen && <section className="smart-filters smart-filters-drawer">
                <div><strong>Smart filters</strong><span>Refine without losing the AI ranking.</span></div>
                <select value={minRating} onChange={(e) => setMinRating(Number(e.target.value))}>
                    <option value="0">Any rating</option><option value="4">4★+</option><option value="4.5">4.5★+</option>
                </select>
                <label><input type="checkbox" checked={instantOnly} onChange={(e) => setInstantOnly(e.target.checked)} /> Under 30 min</label>
                <label><input type="checkbox" checked={verifiedOnly} onChange={(e) => setVerifiedOnly(e.target.checked)} /> Verified source</label>
                <input value={feature} onChange={(e) => setFeature(e.target.value)} placeholder="Feature e.g. ANC" />
            </section>}

            <section className="products-section">
                <div className="section-heading">
                    <div>
                        <span className="eyebrow">SEARCH RESULTS</span>
                        <h2>Best matches for you</h2>
                        <p className="section-subtitle">
                            Sorted by local price by default. Use the controls for best match, ratings or review volume.
                        </p>
                    </div>

                    <div className="results-controls">
                        <div className="result-tabs">
                            <button className={sortMode === "best" ? "active" : ""} onClick={() => setSortMode("best")}><Sparkles size={13}/> Best overall</button>
                            <button className={sortMode === "price_low" ? "active" : ""} onClick={() => setSortMode("price_low")}>Lowest price</button>
                            <button className={sortMode === "rating" ? "active" : ""} onClick={() => setSortMode("rating")}>Top rated</button>
                        </div>
                        <label className="sort-control">
                            <span>Sort</span>
                            <select value={sortMode} onChange={(event) => setSortMode(event.target.value)}>
                                <option value="price_low">Price: Low to High</option>
                                <option value="price_high">Price: High to Low</option>
                                <option value="best">Best Match</option>
                                <option value="rating">Top Rated</option>
                                <option value="reviews">Most Reviewed</option>
                            </select>
                        </label>
                        <span className="results-count">{products.length} results</span>
                    </div>
                </div>

                {products.length === 0 ? (
                    <div className="empty-card">
                        <div className="empty-icon">
                            <PackageSearch size={28} />
                        </div>

                        <h3>No products returned by the merchants</h3>

                        <p>
                            The search reached the backend, but the merchants
                            did not return a matching catalog item. Try a broader
                            product name or refresh the session.
                        </p>

                        <button
                            className="secondary-button"
                            onClick={onRefresh}
                            disabled={loading}
                        >
                            <RefreshCw size={15} />
                            Refresh search
                        </button>
                    </div>
                ) : (
                    <div className="results-workspace">
                        <aside className="results-filter-rail">
                            <div className="filter-rail-head"><div><span className="eyebrow">REFINE</span><strong>Smart filters</strong></div><button onClick={() => { setMinRating(0); setInstantOnly(false); setVerifiedOnly(false); setFeature(""); }}>Reset</button></div>
                            <label className="filter-label">Rating<select value={minRating} onChange={(e) => setMinRating(Number(e.target.value))}><option value="0">Any rating</option><option value="4">4★ & above</option><option value="4.5">4.5★ & above</option></select></label>
                            <label className="filter-check"><input type="checkbox" checked={instantOnly} onChange={(e) => setInstantOnly(e.target.checked)} /><span><b>Fast delivery</b><small>30 min or less</small></span></label>
                            <label className="filter-check"><input type="checkbox" checked={verifiedOnly} onChange={(e) => setVerifiedOnly(e.target.checked)} /><span><b>Verified sources</b><small>Higher trust offers</small></span></label>
                            <label className="filter-label">Must-have feature<input value={feature} onChange={(e) => setFeature(e.target.value)} placeholder="e.g. ANC, 5G" /></label>
                            <div className="filter-tip"><Sparkles size={14}/><span><b>AI ranking stays on</b> — filters narrow the results without hiding ShopMind's recommendation logic.</span></div>
                        </aside>
                        <div className={`products-grid ${viewMode === "list" ? "products-list-view" : ""}`}>
                        {products.slice(0, 12).map((product, index) => (
                            <ProductCard
                                key={`${product.merchant_id}-${product.product_id || product.id || index}`}
                                product={product}
                                recommended={
                                    recommended &&
                                    product.product_id === recommended.product_id &&
                                    product.merchant_id === recommended.merchant_id
                                }
                                compareSelected={compareItems.some((item) => `${item.merchant_id || "merchant"}:${item.product_id || item.id || item.name}` === `${product.merchant_id || "merchant"}:${product.product_id || product.id || product.name}`)}
                                onToggleCompare={toggleCompare}
                                onSelect={selectProduct}
                            />
                        ))}
                        </div>
                    </div>
                )}
            </section>

            {compareItems.length > 0 && (
                <section className="compare-tray">
                    <div className="compare-tray-title"><GitCompareArrows size={18}/><div><strong>Compare deals</strong><span>{compareItems.length}/3 selected</span></div></div>
                    <div className="compare-tray-items">{compareItems.map((item) => <button key={`${item.merchant_id}:${item.product_id || item.id || item.name}`} onClick={() => toggleCompare(item)}><span>{item.name}</span><X size={12}/></button>)}</div>
                    <button className="primary-button" onClick={() => document.querySelector('.fallback-comparison, .comparison-section')?.scrollIntoView({ behavior: 'smooth', block: 'start' })} disabled={compareItems.length < 2}><GitCompareArrows size={15}/> Compare now</button>
                </section>
            )}

            {entries.map((entry) => (
                <ComparisonTable
                    key={entry.product_query}
                    entry={entry}
                />
            ))}

            {entries.length === 0 && products.length > 0 && (
                <section className="comparison-section fallback-comparison">
                    <div className="section-heading">
                        <div>
                            <span className="eyebrow">MERCHANT COMPARISON</span>
                            <h2>Available offers</h2>
                            <p className="section-subtitle">
                                Showing the products returned directly by the merchants.
                            </p>
                        </div>
                    </div>

                    <ComparisonTable
                        entry={{
                            product_query:
                                session?.request?.query || "Your search",
                            merchant_results: products.slice(0, 12),
                            recommended,
                            best_price: [...products].sort(
                                (a, b) =>
                                    Number(a.price || Infinity) -
                                    Number(b.price || Infinity)
                            )[0],
                            best_shipping: products[0],
                        }}
                    />
                </section>
            )}

            {optimization?.items?.length > 0 && (
                <section className="optimization-card">
                    <div className="optimization-icon">
                        <CheckCircle2 size={24} />
                    </div>

                    <div>
                        <span className="eyebrow">SMART ORDER PLAN</span>
                        <h2>Best purchase plan</h2>
                        <p>
                            {optimization.reasoning ||
                                "ShopMind AI selected the best available combination."}
                        </p>
                    </div>

                    <div className="optimization-total">
                        <span>Grand total</span>
                        <strong>
                            {formatMoney(optimization.grand_total, optimization.display_currency)}
                        </strong>
                    </div>
                </section>
            )}

            {compareItems.length > 0 && (
                <div className="compare-tray">
                    <div className="compare-tray-title"><GitCompareArrows size={17}/><div><strong>Compare products</strong><span>{compareItems.length}/3 selected</span></div></div>
                    <div className="compare-tray-items">{compareItems.map((item) => <button key={`${item.merchant_id}-${item.product_id || item.id || item.name}`} onClick={() => toggleCompare(item)} title="Remove from comparison"><span>{item.name}</span><X size={13}/></button>)}</div>
                    <button className="primary-button" onClick={() => document.querySelector(".comparison-section")?.scrollIntoView({ behavior: "smooth" })} disabled={compareItems.length < 2}><GitCompareArrows size={15}/> Compare {compareItems.length < 2 ? "2+" : "now"}</button>
                </div>
            )}

            {!loading && !error && products.length === 0 && (
                <section className="empty-results-card">
                    <div className="empty-results-icon"><PackageSearch size={28} /></div>
                    <div>
                        <span className="eyebrow">NO MATCHES YET</span>
                        <h3>We could not find a matching offer</h3>
                        <p>Try a broader product name, remove a filter, or start a new search.</p>
                    </div>
                    <button className="primary-button" onClick={onBack}><ArrowLeft size={16} /> New search</button>
                </section>
            )}

            {selectedProduct && (
                <div className="selected-deal">
                    <div>
                        <span>Selected deal</span>
                        <strong>{selectedProduct.name}</strong>
                    </div>
                    <strong>
                        {formatMoney(
                            selectedProduct.display_price ?? selectedProduct.price,
                            selectedProduct.display_currency || selectedProduct.currency
                        )}
                    </strong>
                </div>
            )}
        </main>
    );
}

function InsightCard({ icon, label, value, note }) {
    return <div className="insight-card"><div className="insight-icon">{icon}</div><div><span>{label}</span><strong>{value}</strong><small>{note}</small></div></div>;
}

function formatMoney(value, currency = "INR") {
    const number = Number(value);

    if (!Number.isFinite(number)) return "—";

    try {
        return new Intl.NumberFormat(undefined, {
            style: "currency",
            currency: currency || "USD",
            maximumFractionDigits: 2,
        }).format(number);
    } catch {
        return `${currency || "USD"} ${number.toLocaleString()}`;
    }
}
