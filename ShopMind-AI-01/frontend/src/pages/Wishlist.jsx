import React, { useEffect, useState } from "react";
import { Heart, Trash2 } from "lucide-react";
import { getWishlist } from "../services/api";

export default function Wishlist({ onSelect }) {
  const [items, setItems] = useState([]);
  useEffect(() => { getWishlist().then((data) => setItems(data.items || [])).catch(() => {}); }, []);
  return <main className="results-page">
    <section className="query-summary"><span className="eyebrow">SAVED FOR LATER</span><h1><Heart size={24}/> Your Wishlist</h1><p>Products saved in this browser profile.</p></section>
    {items.length === 0 ? <div className="empty-card"><Heart size={30}/><h3>Your wishlist is empty</h3><p>Save a product from any result card.</p></div> : <div className="products-grid">{items.map((p, i) => <article className="product-card" key={p.product_id || i}><div className="product-content"><div className="product-merchant">{p.merchant_name}</div><h3>{p.name}</h3><div className="product-price">{new Intl.NumberFormat(undefined,{style:"currency",currency:p.display_currency||p.currency||"USD"}).format(Number(p.display_price??p.price))}</div><button className="primary-button" onClick={() => onSelect?.(p)}>View deal</button></div></article>)}</div>}
  </main>;
}
