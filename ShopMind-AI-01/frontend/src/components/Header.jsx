import React from "react";
import {
    ShoppingBag,
    Sparkles,
    Activity,
    MapPin,
    Heart,
    BarChart3,
} from "lucide-react";

export default function Header({
    backendOnline = false,
    onHome,
    onWishlist,
    onAdmin,
    locationContext = null,
}) {
    return (
        <header className="site-header">
            <div className="header-inner">
                <button
                    className="brand"
                    onClick={onHome}
                >
                    <div className="brand-icon">
                        <ShoppingBag size={21} />
                    </div>

                    <div>
                        <div className="brand-name">
                            ShopMind <span>AI</span>
                        </div>

                        <div className="brand-tagline">
                            Intelligent shopping
                        </div>
                    </div>
                </button>

                <nav className="desktop-nav" aria-label="Primary navigation">
                    <button onClick={onHome}>Discover</button>
                    <button onClick={onWishlist}>Wishlist</button>
                    <button onClick={onAdmin}>Analytics</button>
                </nav>
                <div className="header-actions">
                    <button className="icon-button" onClick={onWishlist} title="Wishlist"><Heart size={17}/></button>
                    <button className="icon-button" onClick={onAdmin} title="Admin analytics"><BarChart3 size={17}/></button>
                </div>

                <div className="header-location"><MapPin size={13}/><span>{locationContext?.label || "Set location"}</span></div>

                <div className="header-status">
                    <Activity size={15} />

                    <span>
                        {backendOnline
                            ? "AI Online"
                            : "Connecting..."}
                    </span>

                    <span
                        className={`status-dot ${backendOnline ? "online" : "offline"
                            }`}
                    />
                </div>
            </div>
        </header>
    );
}