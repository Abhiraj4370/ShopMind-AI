import React from "react";
import { productImageFallback, productImageUrl } from "./productMedia";
import {
    Trophy,
    Truck,
    Package,
} from "lucide-react";

function money(value, currency = "INR") {
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

export default function ComparisonTable({
    entry,
}) {
    if (!entry) {
        return null;
    }

    const products =
        entry.merchant_results || [];

    return (
        <section className="comparison-section">
            <div className="section-heading">
                <div>
                    <span className="eyebrow">
                        Smart Comparison
                    </span>

                    <h2>
                        Compare{" "}
                        {entry.product_query}
                    </h2>
                </div>

                <div className="comparison-count">
                    {products.length} products
                </div>
            </div>

            <div className="comparison-table-wrapper">
                <table className="comparison-table">
                    <thead>
                        <tr>
                            <th>Product</th>
                            <th>Merchant</th>
                            <th>Price</th>
                            <th>Shipping</th>
                            <th>Availability</th>
                            <th>AI Score</th>
                        </tr>
                    </thead>

                    <tbody>
                        {products.map((product) => (
                            <tr
                                key={`${product.merchant_id}-${product.product_id}`}
                            >
                                <td>
                                    <div className="comparison-product-cell">
                                        <img src={productImageUrl(product)} alt="" onError={(event) => { if (event.currentTarget.dataset.fallbackApplied) return; event.currentTarget.dataset.fallbackApplied = "true"; event.currentTarget.src = productImageFallback(product); }} />
                                        <div><strong>{product.name}</strong><span>{product.source_name || product.merchant_name || "Marketplace"}</span></div>
                                    </div>
                                </td>

                                <td>
                                    {product.merchant_name}
                                </td>

                                <td className="table-price">
                                    {money(product.display_price ?? product.price, product.display_currency || product.currency)}
                                </td>

                                <td>
                                    {product.shipping_options
                                        ?.length
                                        ? money(
                                            product.shipping_options[0].display_price ??
                                                product.shipping_options[0].price,
                                            product.shipping_options[0].display_currency ||
                                                product.display_currency ||
                                                product.currency
                                        )
                                        : "—"}
                                </td>

                                <td>
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
                                </td>

                                <td>
                                    <span className="score">
                                        {(Number(product.score || 0) <= 1 ? Number(product.score || 0) * 100 : Number(product.score || 0)).toFixed(0)}
                                    </span>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>

            {entry.recommended && (
                <div className="comparison-recommendation">
                    <Trophy size={20} />

                    <div>
                        <strong>
                            Best Overall
                        </strong>

                        <span>
                            {entry.recommended.name} from{" "}
                            {entry.recommended.merchant_name}
                        </span>
                    </div>
                </div>
            )}

            {entry.best_shipping && (
                <div className="mini-highlight">
                    <Truck size={17} />

                    <span>
                        Best shipping:{" "}
                        <strong>
                            {entry.best_shipping.name}
                        </strong>
                    </span>
                </div>
            )}

            {entry.best_price && (
                <div className="mini-highlight">
                    <Package size={17} />

                    <span>
                        Lowest price:{" "}
                        <strong>
                            {money(
                                entry.best_price.display_price ??
                                    entry.best_price.price,
                                entry.best_price.display_currency ||
                                    entry.best_price.currency
                            )}
                        </strong>
                    </span>
                </div>
            )}
        </section>
    );
}