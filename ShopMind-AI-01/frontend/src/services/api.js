const API_BASE = "/api/v1";

function userId() {
    let id = window.localStorage.getItem("shopmind_user_id");
    if (!id) {
        id = globalThis.crypto?.randomUUID?.() || `guest-${Date.now()}-${Math.random().toString(36).slice(2)}`;
        window.localStorage.setItem("shopmind_user_id", id);
    }
    return id;
}

async function request(url, options = {}) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), options.timeoutMs || 20000);
    const { timeoutMs: _timeoutMs, ...fetchOptions } = options;
    try {
        const response = await fetch(url, {
            ...fetchOptions,
            headers: {
                "Content-Type": "application/json",
                "X-ShopMind-User-Id": userId(),
                ...(fetchOptions.headers || {}),
            },
            signal: controller.signal,
        });
        if (!response.ok) {
            let message = `Request failed: ${response.status}`;
            try { const data = await response.json(); if (data.detail) message = data.detail; } catch {}
            throw new Error(message);
        }
        return response.status === 204 ? null : response.json();
    } catch (error) {
        if (error?.name === "AbortError") throw new Error("The request timed out. Please try again.");
        throw error;
    } finally { window.clearTimeout(timeout); }
}

export async function createShoppingSession(query, location = null, filters = {}) {
    return request(`${API_BASE}/shop`, {
        method: "POST",
        body: JSON.stringify({ query, filters, ...(filters?.postal_code ? { postal_code: filters.postal_code } : {}),
            ...(Number.isFinite(Number(location?.latitude)) ? { latitude: Number(location.latitude) } : {}),
            ...(Number.isFinite(Number(location?.longitude)) ? { longitude: Number(location.longitude) } : {}),
        }),
    });
}
export async function getShoppingSession(sessionId, sessionToken) { return request(`${API_BASE}/shop/${sessionId}`, { headers: sessionToken ? { "X-ShopMind-Session-Token": sessionToken } : {} }); }
export async function confirmShoppingSession(sessionId, sessionToken) { return request(`${API_BASE}/shop/${sessionId}/confirm`, { method: "POST", headers: sessionToken ? { "X-ShopMind-Session-Token": sessionToken } : {} }); }
export async function cancelShoppingSession(sessionId, sessionToken) { return request(`${API_BASE}/shop/${sessionId}/cancel`, { method: "POST", headers: sessionToken ? { "X-ShopMind-Session-Token": sessionToken } : {} }); }
export async function healthCheck() { const controller = new AbortController(); const timer = window.setTimeout(() => controller.abort(), 5000); let response; try { response = await fetch("/health", { signal: controller.signal }); } finally { window.clearTimeout(timer); } if (!response.ok) throw new Error("Backend is unavailable"); return response.json(); }
export function getLiveLocation() { return new Promise((resolve, reject) => { if (!navigator.geolocation) return reject(new Error("Live location is not supported by this browser.")); navigator.geolocation.getCurrentPosition(p => resolve({ latitude:p.coords.latitude, longitude:p.coords.longitude, accuracy:p.coords.accuracy }), reject, { enableHighAccuracy:true, timeout:8000, maximumAge:120000 }); }); }
export async function resolveLiveLocation(location) { const params = new URLSearchParams({ latitude:String(location.latitude), longitude:String(location.longitude) }); return request(`${API_BASE}/location/resolve?${params.toString()}`, { timeoutMs:10000 }); }
export async function getWishlist() { return request(`${API_BASE}/wishlist`); }
export async function addWishlist(product) { return request(`${API_BASE}/wishlist`, { method:"POST", body:JSON.stringify(product) }); }
export async function getAlerts() { return request(`${API_BASE}/alerts`); }
export async function createPriceAlert(product, targetPrice) { return request(`${API_BASE}/alerts?${new URLSearchParams(targetPrice == null ? {} : { target_price:String(targetPrice) })}`, { method:"POST", body:JSON.stringify(product) }); }
export async function getPriceHistory(fingerprint) { return request(`${API_BASE}/products/price-history?${new URLSearchParams({ fingerprint })}`); }
export async function chatShopping(message) { return request(`${API_BASE}/shop/chat`, { method:"POST", body:JSON.stringify({ message }) }); }
