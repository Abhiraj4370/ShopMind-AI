import React from "react";
import {
    Sparkles,
    Trophy,
    ShieldCheck,
} from "lucide-react";

function formatPrice(value, currency = "USD") {
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

export default function RecommendationCard({
    product,
}) {
    if (!product) {
        return null;
    }

    return (
        <section className="recommendation-card">
            <div className="recommendation-icon">
                <Trophy size={24} />
            </div>

            <div className="recommendation-main">
                <div className="recommendation-label">
                    <Sparkles size={15} />
                    ShopMind AI Recommendation
                </div>

                <h2>{product.name}</h2>

                <p>
                    Recommended from{" "}
                    <strong>
                        {product.merchant_name}
                    </strong>{" "}
                    based on price, availability,
                    shipping and product relevance.
                </p>

                <div className="recommendation-points">
                    <span><ShieldCheck size={15} /> ShopMind score: {Math.round(Number(product.score || 0) * 100)}/100</span>
                    {product.price_signal?.signal && product.price_signal.signal !== "insufficient_history" && (
                        <span>📈 {product.price_signal.signal.replaceAll("_", " ")}</span>
                    )}
                    <span>
                        <ShieldCheck size={15} />
                        Verified merchant result
                    </span>

                    {product.in_stock && (
                        <span>
                            <ShieldCheck size={15} />
                            Currently in stock
                        </span>
                    )}
                </div>
            </div>

            <div className="recommendation-price">
                <span>Price</span>

                <strong>
                    {formatPrice(product.display_price ?? product.price, product.display_currency || product.currency)}
                </strong>
            </div>
        </section>
    );
}