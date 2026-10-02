import React, { useEffect, useState } from "react";

import Header from "./components/Header";
import LoadingSteps from "./components/LoadingSteps";
import Home from "./pages/Home";
import Results from "./pages/Results";
import ProductDetails from "./pages/ProductDetails";
import Wishlist from "./pages/Wishlist";
import Admin from "./pages/Admin";

import {
    createShoppingSession,
    getShoppingSession,
    confirmShoppingSession,
    cancelShoppingSession,
    healthCheck,
    getLiveLocation,
    resolveLiveLocation,
} from "./services/api";

const TERMINAL_STATES = new Set([
    "completed",
    "failed",
    "awaiting_confirmation",
]);

export default function App() {
    const [page, setPage] = useState("home");
    const [sessionId, setSessionId] = useState(null);
    const [sessionToken, setSessionToken] = useState(null);
    const [session, setSession] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState("");
    const [backendOnline, setBackendOnline] = useState(false);
    const [selectedProduct, setSelectedProduct] = useState(null);
    const [liveLocation, setLiveLocation] = useState(null);
    const [locationStatus, setLocationStatus] = useState("detecting");
    const [locationContext, setLocationContext] = useState(null);

    useEffect(() => {
        checkBackend();
        requestLiveLocation(false);
    }, []);

    async function requestLiveLocation(showError = true) {
        try {
            setLocationStatus("detecting");
            const location = await getLiveLocation();
            setLiveLocation(location);
            try {
                const context = await resolveLiveLocation(location);
                setLocationContext(context);
            } catch {
                setLocationContext(null);
            }
            setLocationStatus("ready");
            return location;
        } catch (err) {
            setLocationStatus("unavailable");
            if (showError) {
                setError("Live location was not available. We will use your region from browser/IP instead.");
            }
            return null;
        }
    }

    async function checkBackend() {
        try {
            await healthCheck();
            setBackendOnline(true);
        } catch {
            setBackendOnline(false);
        }
    }

    async function handleSearch(query, options = {}) {
        setLoading(true);
        setError("");
        setSession(null);
        setSelectedProduct(null);

        try {
            const location = liveLocation || await requestLiveLocation(false);
            const result = await createShoppingSession(query, location, options);

            if (!result?.session_id) {
                throw new Error("Backend did not return a session ID.");
            }

            setSessionId(result.session_id);
            setSessionToken(result.session_token || null);
            setPage("results");

            await pollSession(
                result.session_id,
                result.session_token || null
            );
        } catch (err) {
            setError(
                err?.message ||
                    "Unable to create the shopping session."
            );
            setPage("results");
        } finally {
            setLoading(false);
        }
    }

    async function pollSession(id, token) {
        const maxAttempts = 90;

        let transientFailures = 0;
        for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
            let data;
            try {
                data = await getShoppingSession(id, token);
                transientFailures = 0;
            } catch (pollError) {
                transientFailures += 1;
                if (transientFailures >= 4) throw pollError;
                await new Promise((resolve) => setTimeout(resolve, 1500));
                continue;
            }
            setSession(data);

            const state = String(data?.state || "").toLowerCase();

            // Do not stop at "optimizing": the backend can still finish
            // comparison/optimization and update the session afterwards.
            if (TERMINAL_STATES.has(state)) {
                if (state === "failed" && data?.error) {
                    setError(data.error);
                }
                return data;
            }

            await new Promise((resolve) => setTimeout(resolve, 1000));
        }

        throw new Error(
            "The shopping session is taking longer than expected. Use Refresh to check again."
        );
    }

    async function refreshSession() {
        if (!sessionId) return;

        try {
            setLoading(true);
            setError("");
            const data = await getShoppingSession(sessionId, sessionToken);
            setSession(data);

            if (
                String(data?.state || "").toLowerCase() === "failed" &&
                data?.error
            ) {
                setError(data.error);
            }
        } catch (err) {
            setError(err?.message || "Unable to refresh the session.");
        } finally {
            setLoading(false);
        }
    }

    async function confirmOrder() {
        if (!sessionId || !sessionToken) return;
        try {
            setLoading(true);
            setError("");
            await confirmShoppingSession(sessionId, sessionToken);
            await pollSession(sessionId, sessionToken);
        } catch (err) {
            setError(err?.message || "Unable to confirm the order.");
        } finally {
            setLoading(false);
        }
    }

    async function cancelOrder() {
        if (!sessionId || !sessionToken) return;
        try {
            setLoading(true);
            await cancelShoppingSession(sessionId, sessionToken);
            setSession((current) => current ? { ...current, state: "failed", error: "Cancelled by user." } : current);
        } catch (err) {
            setError(err?.message || "Unable to cancel the session.");
        } finally {
            setLoading(false);
        }
    }

    function goHome() {
        setPage("home");
        setSession(null);
        setSessionId(null);
        setSessionToken(null);
        setSelectedProduct(null);
        setError("");
    }

    function handleProductSelect(product) {
        setSelectedProduct(product);
        setPage("details");
    }

    return (
        <div className="app">
            <Header
                backendOnline={backendOnline}
                onHome={goHome}
                onWishlist={() => setPage("wishlist")}
                onAdmin={() => setPage("admin")}
                locationContext={locationContext}
            />

            {page === "home" && (
                <>
                    <Home
                        onSearch={handleSearch}
                        loading={loading}
                        liveLocation={liveLocation}
                        locationContext={locationContext}
                        locationStatus={locationStatus}
                        onRequestLocation={() => requestLiveLocation(true)}
                    />

                    {loading && (
                        <div className="loading-overlay">
                            <LoadingSteps activeStep={2} />
                        </div>
                    )}
                </>
            )}

            {page === "results" && (
                <Results
                    sessionId={sessionId}
                    session={session}
                    loading={loading}
                    error={error}
                    onBack={goHome}
                    onRefresh={refreshSession}
                    onSelectProduct={handleProductSelect}
                    onConfirm={confirmOrder}
                    onCancel={cancelOrder}
                />
            )}

            {page === "details" && (
                <ProductDetails product={selectedProduct} onBack={() => setPage("results")} />
            )}

            {page === "wishlist" && <Wishlist onSelectProduct={(product) => { setSelectedProduct(product); setPage("details"); }} onSelect={(product) => { setSelectedProduct(product); setPage("details"); }} />}
            {page === "admin" && <Admin />}

            <footer className="site-footer">
                <div>
                    <strong>ShopMind AI</strong>
                    <span>Intelligent shopping, simplified.</span>
                </div>
                <span>AI Shopping Assistant</span>
            </footer>
        </div>
    );
}
