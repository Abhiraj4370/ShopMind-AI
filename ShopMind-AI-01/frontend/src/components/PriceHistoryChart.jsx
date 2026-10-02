import React, { useEffect, useMemo, useState } from "react";
import { Activity, CalendarClock, TrendingDown, TrendingUp } from "lucide-react";
import { getPriceHistory } from "../services/api";

function fingerprint(product) {
    const merchant = String(product?.merchant_id || product?.merchant_name || "").toLowerCase();
    const pid = String(product?.product_id || "").toLowerCase();
    const url = String(product?.url || "").trim().toLowerCase();
    return `${merchant}|${pid}|${url}`;
}

function money(value, currency) {
    const n = Number(value);
    if (!Number.isFinite(n)) return "—";
    try { return new Intl.NumberFormat(undefined, { style: "currency", currency: currency || "INR", maximumFractionDigits: 0 }).format(n); }
    catch { return `${currency || "INR"} ${Math.round(n).toLocaleString()}`; }
}

export default function PriceHistoryChart({ product }) {
    const [history, setHistory] = useState([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        let cancelled = false;
        setLoading(true);
        getPriceHistory(fingerprint(product))
            .then((data) => !cancelled && setHistory(Array.isArray(data?.history) ? data.history : []))
            .catch(() => !cancelled && setHistory([]))
            .finally(() => !cancelled && setLoading(false));
        return () => { cancelled = true; };
    }, [product]);

    const points = useMemo(() => [...history].reverse(), [history]);
    const values = points.map((p) => Number(p.price)).filter(Number.isFinite);
    const current = Number(product?.display_price ?? product?.price);
    if (Number.isFinite(current)) values.push(current);

    const min = Math.min(...values, 0);
    const max = Math.max(...values, 1);
    const latest = values.at(-1);
    const low = values.length ? Math.min(...values) : null;
    const avg = values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
    const chartPoints = points.map((p, i) => {
        const x = points.length <= 1 ? 50 : 4 + (i / (points.length - 1)) * 92;
        const v = Number(p.price);
        const y = 86 - ((v - min) / Math.max(1, max - min)) * 72;
        return `${x.toFixed(2)},${y.toFixed(2)}`;
    }).join(" ");

    return (
        <section className="price-history-card">
            <div className="price-history-head">
                <div>
                    <span className="eyebrow"><Activity size={14} /> PRICE INTELLIGENCE</span>
                    <h3>Is this a good time to buy?</h3>
                </div>
                {product?.price_signal?.signal && product.price_signal.signal !== "insufficient_history" && (
                    <span className={`price-signal ${product.price_signal.signal}`}>
                        {product.price_signal.signal === "good_time_to_buy" ? <TrendingDown size={14} /> : <TrendingUp size={14} />}
                        {product.price_signal.signal.replaceAll("_", " ")}
                    </span>
                )}
            </div>

            {loading ? <div className="history-placeholder">Loading price history…</div> : points.length < 2 ? (
                <div className="history-placeholder">
                    <CalendarClock size={18} /> Not enough captured price points yet. New searches automatically build the history.
                </div>
            ) : (
                <>
                    <div className="history-chart-wrap">
                        <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="history-chart" aria-label="Price history graph">
                            <polyline points={chartPoints} fill="none" stroke="currentColor" strokeWidth="2" vectorEffect="non-scaling-stroke" />
                        </svg>
                    </div>
                    <div className="history-stats">
                        <div><span>Lowest</span><strong>{money(low, product.display_currency || product.currency)}</strong></div>
                        <div><span>Average</span><strong>{money(avg, product.display_currency || product.currency)}</strong></div>
                        <div><span>Current</span><strong>{money(Number.isFinite(latest) ? latest : current, product.display_currency || product.currency)}</strong></div>
                    </div>
                </>
            )}
        </section>
    );
}
