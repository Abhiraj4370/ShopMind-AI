import React, { useState } from "react";
import { ArrowLeft, Bell, ExternalLink, Heart, ShieldCheck, Star, Truck, Zap, CheckCircle2, MapPin, TrendingDown, PackageSearch } from "lucide-react";
import { addWishlist, createPriceAlert } from "../services/api";
import PriceHistoryChart from "../components/PriceHistoryChart";
import { productImageFallback, productImageUrl } from "../components/productMedia";

function formatPrice(value, currency = "INR") {
    const number = Number(value);
    if (!Number.isFinite(number)) return "—";
    try { return new Intl.NumberFormat(undefined, { style: "currency", currency: currency || "INR", maximumFractionDigits: 2 }).format(number); }
    catch { return `${currency || "INR"} ${number.toLocaleString()}`; }
}

function safeUrl(value) {
    try { const u = new URL(value); return /^https?:$/.test(u.protocol) ? u.toString() : ""; } catch { return ""; }
}

export default function ProductDetails({ product, onBack }) {
    const [saved, setSaved] = useState(false);
    if (!product) return (
        <main className="details-page">
            <section className="empty-results-card">
                <div className="empty-results-icon"><PackageSearch size={28} /></div>
                <div><span className="eyebrow">PRODUCT NOT FOUND</span><h3>This product is no longer available in this view.</h3><p>Return to your search results and choose another offer.</p></div>
                <button className="primary-button" onClick={onBack}><ArrowLeft size={16} /> Back to results</button>
            </section>
        </main>
    );

    const price = product.display_price ?? product.price;
    const currency = product.display_currency || product.currency || "INR";
    const eta = product.specs?.delivery_window || (product.eta_minutes ? `${product.eta_minutes} min` : "Source-dependent");
    const url = safeUrl(product.url);

    async function save() { try { await addWishlist(product); setSaved(true); } catch {} }
    async function alert() {
        const raw = window.prompt(`Target price in ${currency} (optional):`, "");
        if (raw === null) return;
        try { await createPriceAlert(product, raw ? Number(raw) : null); window.alert("Price alert saved."); } catch (e) { window.alert(e.message); }
    }

    return (
        <main className="details-page">
            <button className="back-button" onClick={onBack}><ArrowLeft size={17} /> Back to results</button>

            <div className="details-grid">
                <div>
                    <div className="details-image"><img src={productImageUrl(product)} alt={product.name || "Product"} onError={(event) => { if (event.currentTarget.dataset.fallbackApplied) return; event.currentTarget.dataset.fallbackApplied = "true"; event.currentTarget.src = productImageFallback(product); }} /><div className="details-image-overlay"><span>PRODUCT PREVIEW</span><strong>{product.source_name || product.merchant_name || "Verified source"}</strong></div></div>
                    {url && <a className="merchant-link" href={url} target="_blank" rel="noreferrer"><ExternalLink size={14} /> Open on {product.merchant_name}</a>}
                </div>

                <div className="details-content">
                    <span className="merchant-label">{product.source_name || product.merchant_name}</span>
                    <h1>{product.name}</h1>
                    <div className="details-rating"><Star size={17} fill="currentColor" /> {product.rating || "N/A"}<span>· {Number(product.review_count || 0).toLocaleString()} reviews</span></div>
                    <div className="details-price">{formatPrice(price, currency)}</div>

                    <div className="details-verdict">
                        <div><strong>ShopMind Score</strong><span>{Math.round(Math.max(0, Math.min(100, Number(product.score || 0) <= 1 ? Number(product.score || 0) * 100 : Number(product.score || 0))))}/100</span></div>
                        <div><strong>Price signal</strong><span>{(product.price_signal?.signal || "waiting for history").replaceAll("_", " ")}</span></div>
                        <div><strong>Delivery</strong><span>{eta}</span></div>
                    </div>
                    <div className="detail-trust-line"><CheckCircle2 size={14}/> Source verified <span>•</span> <MapPin size={14}/> {product.specs?.location || "Region-aware"} <span>•</span> <TrendingDown size={14}/> Price tracked</div>

                    <p>{product.description || "No additional description available."}</p>

                    <div className="details-benefits">
                        <div><ShieldCheck size={19} /> Verified source</div>
                        <div>{product.specs?.delivery_window || product.eta_minutes ? <Zap size={19} /> : <Truck size={19} />} {eta}</div>
                        <div><Heart size={19} /> {saved ? "Saved to wishlist" : "Personal wishlist"}</div>
                    </div>

                    <div className="details-actions">
                        <button className="primary-button" onClick={save}><Heart size={16} /> {saved ? "Saved" : "Save deal"}</button>
                        <button className="secondary-button" onClick={alert}><Bell size={16} /> Price alert</button>
                        {url && <a className="secondary-button" href={url} target="_blank" rel="noreferrer"><ExternalLink size={16} /> Buy / View</a>}
                    </div>

                    <PriceHistoryChart product={product} />

                    {product.review_summary?.sentiment && (
                        <section className="review-intelligence">
                            <span className="eyebrow">REVIEW INTELLIGENCE</span>
                            <h3>What the rating signals say</h3>
                            <div className="sentiment-bars">
                                {Object.entries(product.review_summary.sentiment).map(([key, value]) => <div key={key}><span>{key}</span><div className="sentiment-track"><i style={{ width: `${Number(value) || 0}%` }} /></div><strong>{value}%</strong></div>)}
                            </div>
                            <p>{product.review_summary.summary}</p>
                        </section>
                    )}

                    {Object.keys(product.specs || {}).length > 0 && (
                        <div className="specifications"><h3>Specifications</h3>{Object.entries(product.specs).map(([key, value]) => <div className="spec-row" key={key}><span>{key}</span><strong>{value}</strong></div>)}</div>
                    )}
                </div>
            </div>
        </main>
    );
}
