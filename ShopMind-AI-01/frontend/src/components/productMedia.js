export function productImageUrl(product) {
    if (product?.image_url) return product.image_url;
    return productImageFallback(product);
}

export function productImageFallback(product) {
    const rawTitle = String(product?.name || "Product").slice(0, 34);
    const rawMerchant = String(product?.merchant_name || product?.source_name || "ShopMind").slice(0, 20);
    const escapeXml = (value) => value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    const title = escapeXml(rawTitle);
    const merchant = escapeXml(rawMerchant);
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="720" height="720" viewBox="0 0 720 720"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#8b7cff"/><stop offset="1" stop-color="#4dd9c0"/></linearGradient></defs><rect width="720" height="720" fill="#0d1220"/><circle cx="575" cy="125" r="210" fill="url(#g)" opacity=".18"/><circle cx="120" cy="615" r="180" fill="#8b7cff" opacity=".06"/><rect x="80" y="126" width="560" height="468" rx="42" fill="#151c2d" stroke="#ffffff" stroke-opacity=".09"/><rect x="120" y="168" width="130" height="24" rx="12" fill="#8b7cff" opacity=".45"/><text x="120" y="322" fill="#f7f8fc" font-family="Arial, sans-serif" font-size="38" font-weight="700">${title}</text><text x="120" y="365" fill="#8894a9" font-family="Arial, sans-serif" font-size="21">${merchant}</text><rect x="120" y="430" width="210" height="56" rx="18" fill="#4dd9c0" opacity=".10"/><text x="143" y="466" fill="#87e7d3" font-family="Arial, sans-serif" font-size="20" font-weight="700">ShopMind visual</text><circle cx="580" cy="516" r="38" fill="#8b7cff" opacity=".16"/><path d="M562 516l12 12 26-30" stroke="#a49cff" stroke-width="8" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
    return `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(svg)}`;
}
