"""Convert product prices to the user's display currency."""

from __future__ import annotations

from shopmind_ai.models import ProductResult
from shopmind_ai.services.currency import (
    CurrencyConverter,
    currency_symbol,
)


class RegionalPricingService:
    """Converts merchant prices while preserving original values."""

    def __init__(
        self,
        converter: CurrencyConverter | None = None,
    ) -> None:
        self.converter = converter or CurrencyConverter()

    async def convert_product(
        self,
        product: ProductResult,
        display_currency: str,
    ) -> ProductResult:
        target = display_currency.upper()
        source = (product.currency or "USD").upper()

        product.original_price = product.price
        product.original_currency = source

        if source == target:
            converted = product.price
        else:
            converted = await self.converter.convert(
                product.price,
                source,
                target,
            )

        product.display_price = converted
        product.display_currency = target
        product.display_symbol = currency_symbol(target)

        for option in product.shipping_options:
            shipping_source = source
            if shipping_source == target:
                shipping_converted = option.price
            else:
                shipping_converted = await self.converter.convert(
                    option.price,
                    shipping_source,
                    target,
                )
            option.display_price = shipping_converted
            option.display_currency = target

        return product

    async def convert_products(
        self,
        products: list[ProductResult],
        display_currency: str,
    ) -> list[ProductResult]:
        for product in products:
            await self.convert_product(product, display_currency)
        return products