import React from "react";
import {
    Star,
    Truck,
    CheckCircle,
    ShoppingCart,
    ExternalLink,
    Heart,
    Bell,
    GitCompareArrows,
} from "lucide-react";
import { addWishlist, createPriceAlert } from "../services/api";
import { productImageFallback, productImageUrl } from "./productMedia";

function safeExternalUrl(value) {
    try {
        const url = new URL(value);
        return url.protocol === "https:" || url.protocol === "http:"
            ? url.toString()
            : "";
    } catch {
        return "";
    }
}

function formatPrice(price, currency = "INR") {
    const value = Number(price);
    if (!Number.isFinite(value)) return "—";

    try {
        return new Intl.NumberFormat(undefined, {
            style: "currency",
            currency: currency || "USD",
            maximumFractionDigits: 2,
        }).format(value);
    } catch {
        return `${currency || "USD"} ${value.toLocaleString()}`;
    }
}

function normalizedScore(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return 0;
    return Math.round(Math.max(0, Math.min(100, n <= 1 ? n * 100 : n)));
}

export default function ProductCard({
    product,
    recommended = false,
    compareSelected = false,
    onToggleCompare,
    onSelect,
}) {
    const image = productImageUrl(product);

    return (
        <article
            className={`product-card ${recommended
                    ? "recommended-product"
                    : ""
                }`}
        >
            {recommended && (
                <div className="recommend-badge">
                    <CheckCircle size={14} />
                    AI Recommended
                </div>
            )}

            <div className="product-image-wrap">
                <img
                    src={image}
                    alt={product.name || "Product"}
                    className="product-image"
                    loading="lazy"
                    decoding="async"
                    onError={(event) => {
                        if (event.currentTarget.dataset.fallbackApplied) return;
                        event.currentTarget.dataset.fallbackApplied = "true";
                        event.currentTarget.src = productImageFallback(product);
                    }}
                />
                <div className="product-image-topline">
                    <span className="product-visual-badge">{recommended ? "BEST VALUE" : "SMART MATCH"}</span>
                    {product.eta_minutes && <span className="product-eta-badge"><Zap size={11}/> {product.eta_minutes} min</span>}
                </div>
                <div className="product-image-score">
                    <strong>{normalizedScore(product.score)}</strong>
                    <span>ShopMind</span>
                </div>
            </div>

            <div className="product-content">
                <div className="product-merchant">
                    {product.merchant_name}
                </div>

                <h3>{product.name}</h3>

                <p className="product-description">
                    {product.description ||
                        "Product details available from merchant."}
                </p>

                <div className="product-meta">
                    <span className="rating">
                        <Star
                            size={15}
                            fill="currentColor"
                        />

                        {product.rating ? product.rating.toFixed?.(1) ?? product.rating : "N/A"}
                        {Number(product.review_count || 0) > 0 && (
                            <small>({Number(product.review_count).toLocaleString()})</small>
                        )}
                    </span>

                    <span
                        className={
                            product.in_stock
                                ? "stock"
                                : "out-stock"
                        }
                    >
                        {product.in_stock
                            ? "In Stock"
                            : "Out of Stock"}
                    </span>
                </div>

                <div className="product-price">
                    {formatPrice(
                        product.display_price ?? product.price,
                        product.display_currency || product.currency
                    )}
                </div>

                {product.source_name && (
                    <div className="shipping-info">
                        <CheckCircle size={15} />
                        {product.source_name}
                        {product.trust_score
                            ? ` · ${Math.round(Number(product.trust_score) * 100)}% source trust`
                            : ""}
                    </div>
                )}

                <div className="product-features">
                    {product.specs &&
                        Object.entries(product.specs)
                            .filter(([key, value]) => value && key !== "location" && key !== "availability")
                            .slice(0, 5)
                            .map(([key, value]) => (
                                <span key={key}>
                                    {key}: {value}
                                </span>
                            ))}
                </div>

                {product.specs?.location && (
                    <div className="shipping-info location-result">
                        📍 Near {product.specs.location}
                    </div>
                )}

                <div className="shipping-info">
                    <Truck size={15} />

                    {product.specs?.delivery_window
                        ? `Quick delivery window: ${product.specs.delivery_window}`
                        : product.shipping_options?.length
                        ? `Shipping from ${formatPrice(
                            product.shipping_options[0].display_price ?? product.shipping_options[0].price,
                            product.shipping_options[0].display_currency || product.display_currency || product.currency
                        )}`
                        : "Shipping available"}
                </div>

                <div className="product-actions">
                    <button className="icon-button" title="Save to wishlist" onClick={async () => { try { await addWishlist(product); } catch {} }}>
                        <Heart size={16} />
                    </button>
                    <button className={`icon-button compare-icon ${compareSelected ? "selected" : ""}`} title="Add to compare" onClick={() => onToggleCompare?.(product)}>
                        <GitCompareArrows size={16} />
                    </button>
                    <button className="icon-button" title="Set price alert" onClick={async () => { const raw = window.prompt("Target price (optional)"); if (raw === null) return; try { await createPriceAlert(product, raw ? Number(raw) : null); window.alert("Price alert saved."); } catch (error) { window.alert(error.message); } }}>
                        <Bell size={16} />
                    </button>
                    <button
                        className="primary-button"
                        onClick={() =>
                            onSelect?.(product)
                        }
                    >
                        <ShoppingCart size={16} />
                        View Deal
                    </button>

                    {safeExternalUrl(product.url) && (
                        <a
                            href={safeExternalUrl(product.url)}
                            target="_blank"
                            rel="noreferrer"
                            className="icon-button"
                            title="Open merchant"
                        >
                            <ExternalLink size={17} />
                        </a>
                    )}
                </div>
            </div>
        </article>
    );
}