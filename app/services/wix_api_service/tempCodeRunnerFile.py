if __name__ == "__main__":
    service = WixApiService(
        wix_api_key="IST.eyJraWQiOiJQb3pIX2FDMiIsImFsZyI6IlJTMjU2In0.eyJkYXRhIjoie1wiaWRcIjpcIjIyOTYzYTcwLWRmODAtNGExZC04NDQ2LTRhZjI1YTJhOGFkZVwiLFwiaWRlbnRpdHlcIjp7XCJ0eXBlXCI6XCJhcHBsaWNhdGlvblwiLFwiaWRcIjpcIjk0ZTZkMjExLTEzZDctNGVmMC1iN2ZmLWYzYmM1YTViYzVlYlwifSxcInRlbmFudFwiOntcInR5cGVcIjpcImFjY291bnRcIixcImlkXCI6XCJjMmM5MTllZC1iMWY5LTQwMzgtOTY4Ni1mZjA1YmNiY2RmMDhcIn19IiwiaWF0IjoxNzUxNzEyNzA1fQ.AWhb75PbIx1_pySrRqKYYKRI5rvlnVbQ6gqnvWKhw9JcTezfJjj2hwSbE5EKg8r1AYrFJ-VwxCL6-iatBYv42vsIFJLmx4N9aZiJ7rG9V2MxXSpmjoAyWr7n6zVotQYtfK2sptY93TfiWMuAFj8Iua07N2caBLSlfhH2GZBv633wWHwyPpOfLJu27cqp3b4ijt9SoculdWloGxaeN3jOiaxVfRbA11Y1A4ZPf2mu0RLzOsspv18ABgXL3wUGVJm2ckHGaxMp8O9ZmNaS2ibOydhBwRQw8lcTvaGrFg7KY6APAPiEAfwhbuhM8zLe5BwOJ-6-9fIPtMzfFkpp2MWvUQ",
        wix_site_id="75b93fc8-d16b-4511-a3cb-97b5291f8ea4",
    )
    
    # Пример получения товаров с фильтрацией
    try:
        logger.info("\nПолучение товаров с фильтрацией...")
        product_filter = WixProductFilter(
            sku_list=["8858111000073_50g", "8850348117043_35g"],
            visible=True,
            product_type=ProductType.PHYSICAL
        )
        filtered_products = service.get_all_products(filter_data=product_filter)
        logger.info(f"Получено товаров по фильтру: {len(filtered_products)}")
        if filtered_products:
            logger.info("ID найденных товаров:", " ".join(p.id for p in filtered_products))
        
        logger.info("\nПолучение инвентарей с фильтрацией...")
        inventory_filter = WixInventoryFilter(
            product_ids=[p.id for p in filtered_products] if filtered_products else None
        )
        filtered_inventory = service.get_all_inventory_items(filter_data=inventory_filter)
        logger.info(f"Получено инвентарей по фильтру: {len(filtered_inventory)}")
        if filtered_inventory:
            logger.info("\nДетали инвентарей:")
            for item in filtered_inventory:
                logger.info(f"\nID: {item.id}")
                logger.info(f"Product ID: {item.product_id}")
                logger.info(f"Track Quantity: {item.track_quantity}")
                logger.info(f"Last Updated: {item.last_updated}")
                logger.info("Варианты:")
                for variant in item.variants:
                    logger.info(f"  - Variant ID: {variant.variant_id}")
                    logger.info(f"    В наличии: {variant.in_stock}")
                    logger.info(f"    Количество: {variant.quantity}")
        
    except WixApiError as e:
        logger.error(f"Ошибка: {str(e)}")